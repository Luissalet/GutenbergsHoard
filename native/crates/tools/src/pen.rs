// Modified for Gutenberg: detached engine, own document and product identity.
//! Pen tool (P): click for corner points, drag for smooth points, click the first point to close,
//! Enter/Esc (or switching tools) to finish an open path. Each anchor is its own undo step, as in
//! InDesign.

use gutenberg_doc::SpreadRef;
use gutenberg_geom::{BezPath, Point};
use serde_json::{Value, json};

use crate::{Action, Cursor, Mods, Overlay, PointerEvent, PointerKind, Tool, ToolContext, ToolKey, spread_json};

#[derive(Default)]
pub struct PenTool {
    /// The path being drawn: (item id once created, spread, anchors in spread coords).
    path: Option<u64>,
    spread: Option<SpreadRef>,
    /// Anchors as (p, in, out) in spread coordinates.
    anchors: Vec<(Point, Point, Point)>,
    dragging: bool,
    hover: Point,
}

fn anchor_json(a: &(Point, Point, Point)) -> Value {
    json!({"p": [a.0.x, a.0.y], "in": [a.1.x, a.1.y], "out": [a.2.x, a.2.y]})
}

impl PenTool {
    fn finish(&mut self) -> Vec<Action> {
        self.path = None;
        self.spread = None;
        self.anchors.clear();
        self.dragging = false;
        vec![]
    }
    fn commit_anchor(&mut self) -> Vec<Action> {
        let Some(sr) = self.spread else { return vec![] };
        let Some(last) = self.anchors.last() else { return vec![] };
        match self.path {
            None if self.anchors.len() >= 2 => {
                let anchors: Vec<Value> = self.anchors.iter().map(anchor_json).collect();
                vec![Action::Exec("path.create".into(), json!({"spread": spread_json(sr), "anchors": anchors, "closed": false, "notifyPen": true}))]
            }
            Some(id) => vec![Action::Exec("path.appendAnchor".into(), json!({"id": id, "anchor": anchor_json(last)}))],
            None => vec![],
        }
    }
}

impl Tool for PenTool {
    fn id(&self) -> &'static str {
        "pen"
    }

    fn pointer(&mut self, cx: &ToolContext, ev: &PointerEvent) -> Vec<Action> {
        let Some((sr, sp)) = cx.layout.spread_at(ev.pos) else { return vec![] };
        self.hover = ev.pos;
        // The pen continues on the spread where the path started.
        let sp = match self.spread {
            Some(s) if s != sr => cx.layout.to_spread(s, ev.pos),
            _ => sp,
        };
        // Pick up the item id created by path.create (the newest selected path).
        if self.path.is_none() && self.anchors.len() >= 2 {
            self.path = cx.selection.items.last().map(|i| i.0);
        }
        match ev.kind {
            PointerKind::Down => {
                // Close on the first anchor.
                if self.anchors.len() >= 2
                    && let Some(first) = self.anchors.first()
                    && (first.0 - sp).hypot() <= cx.tol(6.0)
                {
                    let out = match self.path {
                        Some(id) => vec![Action::Exec("path.close".into(), json!({"id": id}))],
                        None => vec![],
                    };
                    self.finish();
                    return out;
                }
                let mut p = sp;
                if ev.mods.shift
                    && let Some(last) = self.anchors.last()
                {
                    p = last.0 + gutenberg_geom::constrain_angle(p - last.0, 45.0);
                }
                if self.anchors.is_empty() {
                    self.spread = Some(sr);
                }
                self.anchors.push((p, p, p));
                self.dragging = true;
                vec![]
            }
            PointerKind::Drag => {
                if let Some(a) = self.anchors.last_mut() {
                    // Smooth point: out handle follows the pointer, in handle mirrors it.
                    a.2 = sp;
                    a.1 = a.0 - (sp - a.0);
                }
                vec![]
            }
            PointerKind::Up => {
                if !self.dragging {
                    return vec![];
                }
                self.dragging = false;
                self.commit_anchor()
            }
            _ => vec![],
        }
    }

    fn key(&mut self, _cx: &ToolContext, key: ToolKey, _mods: Mods) -> Vec<Action> {
        match key {
            ToolKey::Enter | ToolKey::Escape => {
                let had = !self.anchors.is_empty();
                self.finish();
                if had { vec![Action::Exec("selection.set".into(), json!({"ids": []}))] } else { vec![] }
            }
            _ => vec![],
        }
    }

    fn overlays(&self, cx: &ToolContext) -> Vec<Overlay> {
        let Some(sr) = self.spread else { return vec![] };
        let xf = cx.layout.xf(sr);
        let mut out = Vec::new();
        if let Some(last) = self.anchors.last()
            && !self.dragging
        {
            // Rubber band to the pointer.
            out.push(Overlay::Line { a: xf * last.0, b: self.hover, color: [79, 153, 255], dashed: true });
        }
        if self.path.is_none() && self.anchors.len() == 1 {
            let a = self.anchors[0];
            out.push(Overlay::Line { a: xf * a.1, b: xf * a.2, color: [79, 153, 255], dashed: false });
        }
        if self.dragging
            && let Some(a) = self.anchors.last()
        {
            out.push(Overlay::Line { a: xf * a.1, b: xf * a.2, color: [79, 153, 255], dashed: false });
            let _ = BezPath::new();
        }
        out
    }

    fn cursor(&self, _cx: &ToolContext, _p: Point, _m: Mods) -> Cursor {
        Cursor::Pen
    }

    fn busy(&self) -> bool {
        !self.anchors.is_empty()
    }
}
