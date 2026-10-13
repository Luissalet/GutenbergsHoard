// Modified for Gutenberg: detached engine, own document and product identity.
//! Frame and shape tools (Rectangle/Ellipse/Polygon Frame, Rectangle/Ellipse/Polygon, Line).
//! Drag to draw (Shift = square/45°, Alt = from centre); click opens the size dialog.

use gutenberg_geom::{Point, Rect};
use serde_json::json;

use crate::{Action, Cursor, Mods, Overlay, PointerEvent, PointerKind, Tool, ToolContext, rect_json, spread_json};

pub struct FrameTool {
    id: &'static str,
    start: Option<Point>,
    cur: Point,
    active: bool,
    guides: Vec<crate::Overlay>,
    /// Gridify: columns and rows (arrow keys while dragging), and the last drawn rect.
    grid: (u32, u32),
    last: Option<(serde_json::Value, Rect)>,
}

impl FrameTool {
    pub fn new(id: &str) -> Self {
        let id = crate::tool_info(id).map(|t| t.id).unwrap_or("rectangleFrame");
        Self { id, start: None, cur: Point::ZERO, active: false, guides: vec![], grid: (1, 1), last: None }
    }

    /// The preview for `r`: one frame, or a grid of them.
    fn preview(&self, spread: serde_json::Value, r: Rect) -> Action {
        let (shape, content) = self.kind();
        let (c, rw) = self.grid;
        if c * rw > 1 {
            Action::Preview(
                "frame.grid".into(),
                json!({"spread": spread, "shape": shape, "content": content, "rect": rect_json(r), "cols": c, "rows": rw}),
            )
        } else {
            Action::Preview("frame.create".into(), json!({"spread": spread, "shape": shape, "content": content, "rect": rect_json(r)}))
        }
    }
    fn kind(&self) -> (&'static str, &'static str) {
        match self.id {
            "rectangleFrame" => ("rectangle", "graphic"),
            "ellipseFrame" => ("ellipse", "graphic"),
            "polygonFrame" => ("polygon", "graphic"),
            "rectangle" => ("rectangle", "unassigned"),
            "ellipse" => ("ellipse", "unassigned"),
            "polygon" => ("polygon", "unassigned"),
            _ => ("line", "unassigned"),
        }
    }
}

pub fn drag_rect(a: Point, b: Point, m: Mods) -> Rect {
    let (mut dx, mut dy) = (b.x - a.x, b.y - a.y);
    if m.shift {
        let s = dx.abs().max(dy.abs());
        dx = s * dx.signum();
        dy = s * dy.signum();
    }
    if m.alt {
        Rect::new(a.x - dx.abs(), a.y - dy.abs(), a.x + dx.abs(), a.y + dy.abs())
    } else {
        Rect::from_points(a, Point::new(a.x + dx, a.y + dy))
    }
}

impl Tool for FrameTool {
    fn id(&self) -> &'static str {
        self.id
    }

    fn pointer(&mut self, cx: &ToolContext, ev: &PointerEvent) -> Vec<Action> {
        let (shape, content) = self.kind();
        match ev.kind {
            PointerKind::Down => {
                let pos = match cx.layout.spread_at(ev.pos) {
                    Some((sr, sp)) if cx.snap => cx.layout.to_canvas(sr, crate::snap::snap_point(cx, sr, sp).0),
                    _ => ev.pos,
                };
                self.start = Some(pos);
                self.cur = ev.pos;
                self.active = false;
                self.grid = (1, 1);
                self.last = None;
                vec![]
            }
            PointerKind::Drag => {
                let Some(a) = self.start else { return vec![] };
                self.cur = ev.pos;
                if !self.active && (ev.pos - a).hypot() < cx.tol(3.0) {
                    return vec![];
                }
                let Some((sr, sa)) = cx.layout.spread_at(a) else { return vec![] };
                let mut ev = *ev;
                self.guides.clear();
                if cx.snap && !ev.mods.shift {
                    let (p, g) = crate::snap::snap_point(cx, sr, cx.layout.to_spread(sr, ev.pos));
                    ev.pos = cx.layout.to_canvas(sr, p);
                    self.guides = g;
                }
                let ev = &ev;
                let mut out = vec![];
                if !self.active {
                    self.active = true;
                    out.push(Action::Begin(format!(
                        "Create {}",
                        crate::tool_info(self.id).map(|t| t.label.trim_end_matches(" Tool")).unwrap_or("Frame")
                    )));
                }
                if shape == "line" {
                    let mut b = cx.layout.to_spread(sr, ev.pos);
                    if ev.mods.shift {
                        let v = b - sa;
                        let v = gutenberg_geom::constrain_angle(v, 45.0);
                        b = sa + v;
                    }
                    out.push(Action::Preview("line.create".into(), json!({"spread": spread_json(sr), "a": [sa.x, sa.y], "b": [b.x, b.y]})));
                } else {
                    let r = drag_rect(sa, cx.layout.to_spread(sr, ev.pos), ev.mods);
                    self.last = Some((spread_json(sr), r));
                    out.push(self.preview(spread_json(sr), r));
                }
                out
            }
            PointerKind::Up => {
                self.guides.clear();
                let was = self.active;
                self.active = false;
                let start = self.start.take();
                if was {
                    return vec![Action::Commit];
                }
                // Click: size dialog.
                if let Some(a) = start
                    && let Some((sr, sa)) = cx.layout.spread_at(a)
                {
                    return vec![Action::Dialog(
                        "frameSize".into(),
                        json!({"spread": spread_json(sr), "shape": shape, "content": content, "x": sa.x, "y": sa.y, "width": 72.0, "height": 72.0}),
                    )];
                }
                vec![]
            }
            _ => vec![],
        }
    }

    fn key(&mut self, _cx: &ToolContext, key: crate::ToolKey, _mods: Mods) -> Vec<Action> {
        // Gridify while dragging: ←/→ columns, ↑/↓ rows.
        if !self.active || self.kind().0 == "line" {
            return vec![];
        }
        let (c, r) = &mut self.grid;
        match key {
            crate::ToolKey::Right => *c += 1,
            crate::ToolKey::Left => *c = (*c).saturating_sub(1).max(1),
            crate::ToolKey::Up => *r += 1,
            crate::ToolKey::Down => *r = (*r).saturating_sub(1).max(1),
            _ => return vec![],
        }
        match self.last.clone() {
            Some((sp, rect)) => vec![self.preview(sp, rect)],
            None => vec![],
        }
    }

    fn overlays(&self, cx: &ToolContext) -> Vec<Overlay> {
        if let (true, Some(a)) = (self.active, self.start) {
            let r = Rect::from_points(a, self.cur);
            let _ = cx;
            let mut v = self.guides.clone();
            v.push(Overlay::Measure { p: self.cur, text: format!("W: {:.0} pt  H: {:.0} pt", r.width(), r.height()) });
            return v;
        }
        vec![]
    }

    fn cursor(&self, _cx: &ToolContext, _p: Point, _m: Mods) -> Cursor {
        Cursor::Crosshair
    }

    fn busy(&self) -> bool {
        self.active
    }
}
