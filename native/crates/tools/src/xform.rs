// Modified for Gutenberg: detached engine, own document and product identity.
//! Rotate (R), Scale (S) and Shear (O) tools: drag around the selection centre (Alt-click sets
//! the reference point elsewhere in a later iteration); Eyedropper (I): click an object to apply
//! its attributes to the selection.

use gutenberg_geom::Point;
use serde_json::json;

use crate::{Action, Cursor, Mods, PointerEvent, PointerKind, Tool, ToolContext};

pub struct XformTool {
    id: &'static str,
    drag: Option<(Point, Point)>,
}

impl XformTool {
    pub fn new(id: &'static str) -> Self {
        Self { id, drag: None }
    }
}

impl Tool for XformTool {
    fn id(&self) -> &'static str {
        self.id
    }
    fn pointer(&mut self, cx: &ToolContext, ev: &PointerEvent) -> Vec<Action> {
        match ev.kind {
            PointerKind::Down => {
                let Some(b) = cx.selection_bounds() else { return vec![] };
                self.drag = Some((b.center(), ev.pos));
                vec![Action::Begin(match self.id {
                    "rotate" => "Rotate".into(),
                    "scale" => "Scale".into(),
                    _ => "Shear".into(),
                })]
            }
            PointerKind::Drag => {
                let Some((c, start)) = self.drag else { return vec![] };
                let (v0, v1) = (start - c, ev.pos - c);
                match self.id {
                    "rotate" => {
                        let mut a = (v1.atan2() - v0.atan2()).to_degrees();
                        if ev.mods.shift {
                            a = (a / 45.0).round() * 45.0;
                        }
                        vec![Action::Preview("transform.rotate".into(), json!({"angle": -a}))]
                    }
                    "scale" => {
                        let (mut sx, mut sy) = (v1.x / v0.x.abs().max(1e-6) * v0.x.signum(), v1.y / v0.y.abs().max(1e-6) * v0.y.signum());
                        if ev.mods.shift {
                            let s = sx.abs().max(sy.abs());
                            sx = s;
                            sy = s;
                        }
                        vec![Action::Preview("transform.scale".into(), json!({"sx": sx, "sy": sy}))]
                    }
                    _ => {
                        let a = ((v1.x - v0.x) / v0.y.abs().max(20.0)).atan().to_degrees();
                        vec![Action::Preview("transform.shear".into(), json!({"angle": a}))]
                    }
                }
            }
            PointerKind::Up => {
                if self.drag.take().is_some() {
                    vec![Action::Commit]
                } else {
                    vec![]
                }
            }
            _ => vec![],
        }
    }
    fn cursor(&self, _cx: &ToolContext, _p: Point, _m: Mods) -> Cursor {
        if self.id == "rotate" { Cursor::Rotate } else { Cursor::Crosshair }
    }
    fn busy(&self) -> bool {
        self.drag.is_some()
    }
}

#[derive(Default)]
pub struct EyedropperTool;

impl Tool for EyedropperTool {
    fn id(&self) -> &'static str {
        "eyedropper"
    }
    fn pointer(&mut self, cx: &ToolContext, ev: &PointerEvent) -> Vec<Action> {
        if ev.kind != PointerKind::Down {
            return vec![];
        }
        let Some((_, id)) = cx.hit(ev.pos) else { return vec![] };
        if cx.selection.items.is_empty() && cx.selection.text.is_none() {
            return vec![Action::Exec("selection.set".into(), json!({"ids": [id.0]}))];
        }
        vec![Action::Exec("object.matchAttributes".into(), json!({"from": id.0}))]
    }
    fn cursor(&self, _cx: &ToolContext, _p: Point, _m: Mods) -> Cursor {
        Cursor::Eyedropper
    }
}
