// Modified for Gutenberg: detached engine, own document and product identity.
//! Gutenberg tools: pointer events in → commands and overlays out.
//!
//! Tools never mutate the document. They emit [`Action`]s the engine executes: `Begin` snapshots
//! the document, each `Preview` re-applies one command on top of the snapshot, `Commit` records
//! the last preview as one undo step. `Exec` runs a command immediately. Every gesture is therefore
//! replayable by the control channel and MCP, and tools are testable without a UI.
//!
//! Pointer positions are **canvas** coordinates (see [`layout::CanvasLayout`]).
#![deny(clippy::unwrap_used, clippy::expect_used, clippy::panic, clippy::unimplemented, clippy::todo, clippy::unreachable)]
#![forbid(unsafe_code)]

mod anchors;
pub mod catalog;
mod frame;
mod gradient;
pub mod layout;
mod nav;
mod pen;
mod pencil;
pub mod select;
pub mod snap;
mod text;
mod xform;

use gutenberg_compose::Cache;
use gutenberg_doc::{Document, Item, ItemId, Selection, SpreadRef};
use gutenberg_geom::{Affine, BezPath, Point, Rect};
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub use catalog::{TOOL_GROUPS, ToolInfo, tool_for_shortcut, tool_info};
pub use layout::CanvasLayout;

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct Mods {
    #[serde(default)]
    pub shift: bool,
    #[serde(default)]
    pub alt: bool,
    /// Command on macOS, Ctrl elsewhere.
    #[serde(default)]
    pub cmd: bool,
    #[serde(default)]
    pub ctrl: bool,
    #[serde(default)]
    pub space: bool,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum PointerKind {
    Down,
    Drag,
    Up,
    Move,
    DoubleClick,
}

#[derive(Clone, Copy, Debug, PartialEq, Serialize, Deserialize)]
pub struct PointerEvent {
    pub kind: PointerKind,
    /// Canvas coordinates.
    pub pos: Point,
    #[serde(default)]
    pub mods: Mods,
}

impl PointerEvent {
    pub fn new(kind: PointerKind, x: f64, y: f64) -> Self {
        Self { kind, pos: Point::new(x, y), mods: Mods::default() }
    }
    pub fn with_mods(mut self, m: Mods) -> Self {
        self.mods = m;
        self
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum ToolKey {
    Enter,
    Escape,
    Backspace,
    Delete,
    Up,
    Down,
    Left,
    Right,
    Home,
    End,
    Tab,
    PageUp,
    PageDown,
}

/// What a tool asks the engine to do.
#[derive(Clone, Debug, PartialEq)]
pub enum Action {
    Begin(String),
    Preview(String, Value),
    Commit,
    Cancel,
    Exec(String, Value),
    /// Ask the UI to open a dialog.
    Dialog(String, Value),
    SwitchTool(String),
    /// Ask the UI to pan/zoom: `{"pan":[dx,dy]}` (screen px) or `{"zoomAt":[x,y], "factor":f}` (canvas).
    View(Value),
}

/// Read-only context a tool sees.
pub struct ToolContext<'a> {
    pub doc: &'a Document,
    pub selection: &'a Selection,
    pub cache: &'a Cache,
    pub layout: &'a CanvasLayout,
    /// Screen pixels per point.
    pub zoom: f64,
    /// Layer new items go on.
    pub layer: gutenberg_doc::LayerId,
    pub snap: bool,
}

impl ToolContext<'_> {
    pub fn tol(&self, px: f64) -> f64 {
        px / self.zoom.max(1e-9)
    }

    /// Frontmost unlocked item under a canvas point.
    pub fn hit(&self, p: Point) -> Option<(SpreadRef, ItemId)> {
        let (sr, sp) = self.layout.spread_at(p)?;
        let SpreadRef::Doc(si) = sr else {
            return self.hit_parent(sr, sp);
        };
        self.doc.hit_item(si, sp, self.tol(4.0)).map(|id| (sr, id))
    }

    /// The parent item showing (not yet overridden) on the document page under `p`:
    /// (absolute page, parent item).
    pub fn hit_parent_on_page(&self, p: Point) -> Option<(usize, ItemId)> {
        let (SpreadRef::Doc(si), sp) = self.layout.spread_at(p)? else { return None };
        let spread = self.doc.spreads.get(si)?;
        let pi = spread.page_at_x(sp.x)?;
        let page = self.doc.first_page_of_spread(si) + pi;
        let (ppi, ppg) = self.doc.parent_page_for(page)?;
        let parent = &self.doc.parents[ppi];
        let pg = &spread.pages[pi];
        let at = sp - gutenberg_geom::Vec2::new(pg.x - parent.pages[ppg].x, 0.0);
        parent
            .items
            .iter()
            .rev()
            .find(|it| !it.locked && !pg.overridden.contains(&it.id) && gutenberg_doc::edit_hit(it, at, self.tol(4.0)))
            .map(|it| (page, it.id))
    }

    fn hit_parent(&self, sr: SpreadRef, sp: Point) -> Option<(SpreadRef, ItemId)> {
        let s = self.doc.spread(sr)?;
        s.items.iter().rev().find(|it| !it.locked && gutenberg_doc::edit_hit(it, sp, self.tol(4.0))).map(|it| (sr, it.id))
    }

    /// Spread-space → canvas transform of the spread holding item `id`.
    pub fn item_canvas_xf(&self, id: ItemId) -> Option<Affine> {
        let loc = self.doc.find(id)?;
        Some(self.layout.xf(loc.spread) * self.doc.parent_xf(&loc))
    }

    pub fn item(&self, id: ItemId) -> Option<&Item> {
        self.doc.item(id)
    }

    /// Canvas bounds of the selected items.
    pub fn selection_bounds(&self) -> Option<Rect> {
        let mut r: Option<Rect> = None;
        for id in &self.selection.items {
            let (Some(it), Some(xf)) = (self.doc.item(*id), self.item_canvas_xf(*id)) else { continue };
            let b = xf.transform_rect_bbox(it.bounds());
            r = Some(r.map_or(b, |r| r.union(b)));
        }
        r
    }
}

/// Visual feedback (canvas coordinates) drawn by the UI.
#[derive(Clone, Debug, PartialEq)]
pub enum Overlay {
    Marquee(Rect),
    /// Preview outline of a frame being drawn.
    Path {
        path: BezPath,
        color: [u8; 3],
        dashed: bool,
    },
    Line {
        a: Point,
        b: Point,
        color: [u8; 3],
        dashed: bool,
    },
    /// Measurement pill near the cursor.
    Measure {
        p: Point,
        text: String,
    },
    /// Smart guide line in the smart-guide colour.
    Guide {
        a: Point,
        b: Point,
    },
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub enum Cursor {
    #[default]
    Arrow,
    ArrowHollow,
    Move,
    Crosshair,
    ResizeH,
    ResizeV,
    ResizeNwSe,
    ResizeNeSw,
    Rotate,
    Pen,
    Text,
    Hand,
    HandGrab,
    ZoomIn,
    ZoomOut,
    Eyedropper,
    LoadedText,
    LoadedGraphic,
    NotAllowed,
}

pub trait Tool: Send {
    fn id(&self) -> &'static str;
    fn pointer(&mut self, cx: &ToolContext, ev: &PointerEvent) -> Vec<Action>;
    fn key(&mut self, _cx: &ToolContext, _key: ToolKey, _mods: Mods) -> Vec<Action> {
        vec![]
    }
    fn overlays(&self, _cx: &ToolContext) -> Vec<Overlay> {
        vec![]
    }
    fn cursor(&self, _cx: &ToolContext, _p: Point, _mods: Mods) -> Cursor {
        Cursor::Arrow
    }
    fn busy(&self) -> bool {
        false
    }
    /// The tool takes typed text (Type tool with a caret): single-key shortcuts are suppressed.
    fn wants_text(&self, _cx: &ToolContext) -> bool {
        false
    }
}

pub fn create(id: &str) -> Box<dyn Tool> {
    match id {
        "selection" => Box::new(select::SelectionTool::new(false)),
        "directSelection" => Box::new(select::SelectionTool::new(true)),
        "rectangleFrame" | "ellipseFrame" | "polygonFrame" | "rectangle" | "ellipse" | "polygon" | "line" => Box::new(frame::FrameTool::new(id)),
        "type" => Box::new(text::TypeTool::default()),
        "verticalType" => Box::new(text::TypeTool::vertical()),
        "pen" => Box::new(pen::PenTool::default()),
        "gradientSwatch" => Box::new(gradient::GradientTool::default()),
        "gradientFeather" => Box::new(gradient::GradientTool::feather()),
        "pencil" => Box::new(pencil::PencilTool::default()),
        "smooth" => Box::new(pencil::PathDragTool::new(false)),
        "erase" => Box::new(pencil::PathDragTool::new(true)),
        "addAnchor" => Box::new(anchors::AnchorTool::new(anchors::Kind::Add)),
        "deleteAnchor" => Box::new(anchors::AnchorTool::new(anchors::Kind::Delete)),
        "convertDirection" => Box::new(anchors::AnchorTool::new(anchors::Kind::Convert)),
        "scissors" => Box::new(anchors::AnchorTool::new(anchors::Kind::Scissors)),
        "rotate" => Box::new(xform::XformTool::new("rotate")),
        "scale" => Box::new(xform::XformTool::new("scale")),
        "shear" => Box::new(xform::XformTool::new("shear")),
        "eyedropper" => Box::new(xform::EyedropperTool),
        "hand" => Box::new(nav::HandTool::default()),
        "placeGun" => Box::new(nav::PlaceGun::default()),
        "zoom" => Box::new(nav::ZoomTool::default()),
        "page" => Box::new(nav::PageTool),
        "typeOnPath" => Box::new(nav::PathTypeTool),
        "gap" => Box::new(nav::GapTool::default()),
        "contentCollector" => Box::new(nav::ConveyorTool::new(false)),
        "contentPlacer" => Box::new(nav::ConveyorTool::new(true)),
        other => Box::new(NoopTool(tool_info(other).map(|t| t.id).unwrap_or("selection"))),
    }
}

/// Placeholder for tools whose behaviour hasn't landed yet.
pub struct NoopTool(&'static str);

impl Tool for NoopTool {
    fn id(&self) -> &'static str {
        self.0
    }
    fn pointer(&mut self, _cx: &ToolContext, _ev: &PointerEvent) -> Vec<Action> {
        vec![]
    }
}

pub(crate) fn rect_json(r: Rect) -> Value {
    serde_json::json!([r.x0, r.y0, r.x1, r.y1])
}

pub(crate) fn spread_json(r: SpreadRef) -> Value {
    serde_json::to_value(r).unwrap_or(Value::Null)
}

#[cfg(test)]
mod tests;
