// Modified for Gutenberg: detached engine, own document and product identity.
//! Selection tool (V) and Direct Selection tool (A).
//!
//! Click selects the frontmost item (Shift toggles), drag moves (Alt duplicates, Shift constrains),
//! the 8 bounding-box handles resize (Shift keeps proportions, Alt from centre, Cmd scales content),
//! empty-canvas drags make a marquee, double-clicking a text frame switches to the Type tool.

use gutenberg_doc::SpreadRef;
use gutenberg_geom::{Point, Rect, Vec2};
use serde_json::{Value, json};

use crate::{Action, Cursor, Mods, Overlay, PointerEvent, PointerKind, Tool, ToolContext, ToolKey, rect_json, spread_json};

#[derive(Clone, Debug)]
enum Drag {
    None,
    Pending { start: Point, hit: bool },
    Move { start: Point, origin_spread: SpreadRef, bounds0: Option<Rect> },
    Resize { handle: usize, start: Point, from: Rect, spread: SpreadRef },
    Rotate { center: Point, start_angle: f64 },
    Marquee { start: Point, cur: Point },
    Anchor { id: u64, si: usize, ai: usize, handle: Option<&'static str>, start: Point },
}

/// Anchor or handle of a selected item under `p` (canvas): (item, subpath, anchor, handle).
pub fn anchor_at(cx: &ToolContext, p: Point) -> Option<(u64, usize, usize, Option<&'static str>)> {
    anchor_at_in(cx, &cx.selection.items, p)
}

/// [`anchor_at`] over the given items.
pub fn anchor_at_in(cx: &ToolContext, ids: &[gutenberg_doc::ItemId], p: Point) -> Option<(u64, usize, usize, Option<&'static str>)> {
    let tol = cx.tol(5.0);
    for id in ids {
        let (Some(it), Some(xf)) = (cx.doc.item(*id), cx.item_canvas_xf(*id)) else { continue };
        let m = xf * it.xf;
        for (si, sp) in it.path.subpaths.iter().enumerate() {
            for (ai, a) in sp.anchors.iter().enumerate() {
                if ((m * a.p) - p).hypot() <= tol {
                    return Some((id.0, si, ai, None));
                }
                if a.has_in() && ((m * a.h_in) - p).hypot() <= tol {
                    return Some((id.0, si, ai, Some("in")));
                }
                if a.has_out() && ((m * a.h_out) - p).hypot() <= tol {
                    return Some((id.0, si, ai, Some("out")));
                }
            }
        }
    }
    None
}

pub struct SelectionTool {
    direct: bool,
    drag: Drag,
    hover_handle: Option<usize>,
    guides: Vec<Overlay>,
}

impl SelectionTool {
    pub fn new(direct: bool) -> Self {
        Self { direct, drag: Drag::None, hover_handle: None, guides: vec![] }
    }
}

/// Handle positions (canvas) of a rect: 0 TL, 1 T, 2 TR, 3 R, 4 BR, 5 B, 6 BL, 7 L.
pub fn handles(r: Rect) -> [Point; 8] {
    let c = r.center();
    [
        Point::new(r.x0, r.y0),
        Point::new(c.x, r.y0),
        Point::new(r.x1, r.y0),
        Point::new(r.x1, c.y),
        Point::new(r.x1, r.y1),
        Point::new(c.x, r.y1),
        Point::new(r.x0, r.y1),
        Point::new(r.x0, c.y),
    ]
}

fn handle_at(cx: &ToolContext, p: Point) -> Option<usize> {
    let b = cx.selection_bounds()?;
    let tol = cx.tol(5.0);
    handles(b).iter().position(|h| (h.x - p.x).abs() <= tol && (h.y - p.y).abs() <= tol)
}

/// Just outside a corner handle of the selection → rotate.
fn rotate_zone(cx: &ToolContext, p: Point) -> Option<Point> {
    let b = cx.selection_bounds()?;
    let inner = cx.tol(5.0);
    let outer = cx.tol(18.0);
    for c in [Point::new(b.x0, b.y0), Point::new(b.x1, b.y0), Point::new(b.x1, b.y1), Point::new(b.x0, b.y1)] {
        let d = (c - p).hypot();
        let outside = p.x < b.x0 || p.x > b.x1 || p.y < b.y0 || p.y > b.y1;
        if d > inner && d <= outer && outside {
            return Some(b.center());
        }
    }
    None
}

/// New rect when dragging `handle` of `from` to `p`.
pub fn resize_rect(from: Rect, handle: usize, p: Point, m: Mods) -> Rect {
    let (mut x0, mut y0, mut x1, mut y1) = (from.x0, from.y0, from.x1, from.y1);
    match handle {
        0 => {
            x0 = p.x;
            y0 = p.y;
        }
        1 => y0 = p.y,
        2 => {
            x1 = p.x;
            y0 = p.y;
        }
        3 => x1 = p.x,
        4 => {
            x1 = p.x;
            y1 = p.y;
        }
        5 => y1 = p.y,
        6 => {
            x0 = p.x;
            y1 = p.y;
        }
        _ => x0 = p.x,
    }
    if m.shift && from.width() > 1e-9 && from.height() > 1e-9 {
        let sx = (x1 - x0) / from.width();
        let sy = (y1 - y0) / from.height();
        let s = if matches!(handle, 1 | 5) {
            sy
        } else if matches!(handle, 3 | 7) || sx.abs() > sy.abs() {
            sx
        } else {
            sy
        };
        let (w, h) = (from.width() * s, from.height() * s);
        match handle {
            0 => {
                x0 = x1 - w;
                y0 = y1 - h;
            }
            2 => {
                x1 = x0 + w;
                y0 = y1 - h;
            }
            3..=5 => {
                x1 = x0 + w;
                y1 = y0 + h;
            }
            6 | 7 => {
                x0 = x1 - w;
                y1 = y0 + h;
            }
            _ => {
                x0 = x1 - w;
                y0 = y1 - h;
            }
        }
    }
    if m.alt {
        let c = from.center();
        let (hw, hh) = ((x1 - x0) / 2.0, (y1 - y0) / 2.0);
        let (hw, hh) = match handle {
            1 | 5 => (from.width() / 2.0, (if handle == 1 { c.y - y0 } else { y1 - c.y })),
            3 | 7 => ((if handle == 7 { c.x - x0 } else { x1 - c.x }), from.height() / 2.0),
            _ => (hw.abs().max((c.x - x0).abs()).max((x1 - c.x).abs()), hh.abs().max((c.y - y0).abs()).max((y1 - c.y).abs())),
        };
        return Rect::new(c.x - hw, c.y - hh, c.x + hw, c.y + hh);
    }
    Rect::new(x0, y0, x1, y1)
}

impl Tool for SelectionTool {
    fn id(&self) -> &'static str {
        if self.direct { "directSelection" } else { "selection" }
    }

    fn pointer(&mut self, cx: &ToolContext, ev: &PointerEvent) -> Vec<Action> {
        let p = ev.pos;
        match ev.kind {
            PointerKind::Move => {
                self.hover_handle = handle_at(cx, p);
                vec![]
            }
            PointerKind::Down => {
                if self.direct
                    && let Some((id, si, ai, handle)) = anchor_at(cx, p)
                {
                    self.drag = Drag::Anchor { id, si, ai, handle, start: p };
                    return vec![Action::Begin(if handle.is_some() { "Move Direction Handle".into() } else { "Move Anchor".into() })];
                }
                if !self.direct
                    && handle_at(cx, p).is_none()
                    && let Some(center) = rotate_zone(cx, p)
                {
                    self.drag = Drag::Rotate { center, start_angle: (p - center).atan2() };
                    return vec![Action::Begin("Rotate".into())];
                }
                if let Some(h) = handle_at(cx, p).filter(|_| !self.direct)
                    && let (Some(b), Some(first)) = (cx.selection_bounds(), cx.selection.items.first())
                    && let Some(loc) = cx.doc.find(*first)
                {
                    // On a turned spread the canvas handle is another one of the spread's.
                    let turns = cx.layout.slot(loc.spread).map_or(0, |s| s.rotation as usize);
                    let handle = (h + 8 - 2 * turns) % 8;
                    self.drag =
                        Drag::Resize { handle, start: p, from: cx.layout.xf(loc.spread).inverse().transform_rect_bbox(b), spread: loc.spread };
                    return vec![Action::Begin("Resize".into())];
                }
                // Cmd+Shift-click a parent item on a page: override it there and select the copy.
                if ev.mods.cmd
                    && ev.mods.shift
                    && cx.hit(p).is_none()
                    && let Some((page, id)) = cx.hit_parent_on_page(p)
                {
                    self.drag = Drag::Pending { start: p, hit: true };
                    return vec![Action::Exec("layout.overrideParentItems".into(), json!({"page": page, "ids": [id.0]}))];
                }
                match cx.hit(p) {
                    Some((sr, id)) => {
                        let id = if self.direct { id } else { cx.doc.top_level_of(id).unwrap_or(id) };
                        let mut out = vec![];
                        if ev.mods.shift {
                            out.push(Action::Exec("selection.toggle".into(), json!({"id": id.0})));
                        } else if !cx.selection.contains(id) {
                            out.push(Action::Exec("selection.set".into(), json!({"ids": [id.0], "content": self.direct})));
                        }
                        self.drag = Drag::Pending { start: p, hit: true };
                        let _ = sr;
                        out
                    }
                    None => {
                        self.drag = Drag::Pending { start: p, hit: false };
                        if ev.mods.shift { vec![] } else { vec![Action::Exec("selection.set".into(), json!({"ids": []}))] }
                    }
                }
            }
            PointerKind::Drag => match self.drag.clone() {
                Drag::Pending { start, hit } => {
                    if (p - start).hypot() < cx.tol(3.0) {
                        return vec![];
                    }
                    if hit && !cx.selection.items.is_empty() {
                        let sr = cx.selection.items.first().and_then(|i| cx.doc.find(*i)).map(|l| l.spread).unwrap_or(SpreadRef::Doc(0));
                        self.drag = Drag::Move { start, origin_spread: sr, bounds0: cx.selection_bounds() };
                        let label = if ev.mods.alt { "Duplicate" } else { "Move" };
                        let mut v = vec![Action::Begin(label.into())];
                        v.extend(self.pointer(cx, ev));
                        v
                    } else {
                        self.drag = Drag::Marquee { start, cur: p };
                        vec![]
                    }
                }
                Drag::Move { start, origin_spread, bounds0 } => {
                    let mut d: Vec2 = p - start;
                    if ev.mods.shift {
                        if d.x.abs() > d.y.abs() {
                            d.y = 0.0;
                        } else {
                            d.x = 0.0;
                        }
                    }
                    self.guides.clear();
                    // The movement in the spread's own coordinates (its view may be turned).
                    let mut ds = cx.layout.delta_to_spread(origin_spread, d);
                    let b0s = bounds0.map(|b| cx.layout.xf(origin_spread).inverse().transform_rect_bbox(b));
                    if cx.snap
                        && let Some(b0) = b0s
                    {
                        let snap = crate::snap::snap_rect(cx, origin_spread, b0 + ds, &cx.selection.items);
                        ds += snap.delta;
                        self.guides = snap.guides;
                    }
                    // Dragging to another spread moves the items there.
                    let target = cx.layout.spread_at(p).map(|(s, _)| s).unwrap_or(origin_spread);
                    let mut params = json!({"dx": ds.x, "dy": ds.y, "copy": ev.mods.alt});
                    if target != origin_spread {
                        // Where the selection's corner lands, in the target spread.
                        let q0 = b0s.map_or(Point::ORIGIN, |b| Point::new(b.x0, b.y0));
                        let landed = cx.layout.to_spread(target, cx.layout.to_canvas(origin_spread, q0 + ds));
                        let dt = landed - q0;
                        params = json!({"dx": dt.x, "dy": dt.y, "copy": ev.mods.alt, "toSpread": spread_json(target)});
                    }
                    vec![Action::Preview("transform.move".into(), params)]
                }
                Drag::Resize { handle, start, from, spread } => {
                    let to = resize_rect(from, handle, cx.layout.to_spread(spread, p), ev.mods);
                    let _ = start;
                    // Space while dragging: Live Distribute (several objects keep their size).
                    let distribute = ev.mods.space && cx.selection.items.len() > 1;
                    vec![Action::Preview(
                        "transform.resize".into(),
                        json!({"from": rect_json(from), "to": rect_json(to), "content": ev.mods.cmd, "distribute": distribute}),
                    )]
                }
                Drag::Marquee { start, .. } => {
                    self.drag = Drag::Marquee { start, cur: p };
                    vec![]
                }
                Drag::Rotate { center, start_angle } => {
                    let mut a = ((p - center).atan2() - start_angle).to_degrees();
                    if ev.mods.shift {
                        a = (a / 45.0).round() * 45.0;
                    }
                    // Screen y points down: a positive screen angle is clockwise.
                    vec![Action::Preview("transform.rotate".into(), json!({"angle": -a}))]
                }
                Drag::Anchor { id, si, ai, handle, start } => {
                    let d = p - start;
                    let mut params = json!({"id": id, "anchors": [[si, ai]], "dx": d.x, "dy": d.y});
                    if let Some(h) = handle {
                        params["handle"] = json!(h);
                    }
                    vec![Action::Preview("path.moveAnchors".into(), params)]
                }
                Drag::None => vec![],
            },
            PointerKind::Up => {
                self.guides.clear();
                let d = std::mem::replace(&mut self.drag, Drag::None);
                match d {
                    Drag::Move { .. } | Drag::Resize { .. } | Drag::Anchor { .. } | Drag::Rotate { .. } => vec![Action::Commit],
                    Drag::Marquee { start, cur } => {
                        let r = Rect::from_points(start, cur);
                        // Items whose bounds intersect the marquee.
                        let mut ids: Vec<Value> = Vec::new();
                        for slot in &cx.layout.slots {
                            let Some(sp) = cx.doc.spread(slot.spread) else { continue };
                            for it in &sp.items {
                                let b = slot.xf.transform_rect_bbox(it.bounds());
                                let locked = it.locked || cx.doc.layer(it.layer).is_some_and(|l| l.locked || !l.visible);
                                if !locked && !it.hidden && b.x0 < r.x1 && b.x1 > r.x0 && b.y0 < r.y1 && b.y1 > r.y0 {
                                    ids.push(Value::from(it.id.0));
                                }
                            }
                        }
                        vec![Action::Exec("selection.set".into(), json!({"ids": ids, "add": ev.mods.shift}))]
                    }
                    _ => vec![],
                }
            }
            PointerKind::DoubleClick => {
                if let Some((_, id)) = cx.hit(p)
                    && cx.doc.item(id).is_some_and(|i| i.is_text_frame())
                {
                    let (sr, sp) = cx.layout.spread_at(p).unwrap_or((SpreadRef::Doc(0), p));
                    let _ = sr;
                    return vec![
                        Action::SwitchTool("type".into()),
                        Action::Exec("text.placeCaret".into(), json!({"frame": id.0, "point": [sp.x, sp.y]})),
                    ];
                }
                vec![]
            }
        }
    }

    fn key(&mut self, cx: &ToolContext, key: ToolKey, mods: Mods) -> Vec<Action> {
        let inc = cx.doc.settings.keyboard_increment * if mods.shift { 10.0 } else { 1.0 };
        let mv = |dx: f64, dy: f64| vec![Action::Exec("transform.move".into(), json!({"dx": dx, "dy": dy, "copy": mods.alt}))];
        if cx.selection.items.is_empty() {
            return vec![];
        }
        match key {
            ToolKey::Left => mv(-inc, 0.0),
            ToolKey::Right => mv(inc, 0.0),
            ToolKey::Up => mv(0.0, -inc),
            ToolKey::Down => mv(0.0, inc),
            ToolKey::Delete | ToolKey::Backspace => vec![Action::Exec("edit.clear".into(), json!({}))],
            ToolKey::Escape => vec![Action::Exec("selection.set".into(), json!({"ids": []}))],
            _ => vec![],
        }
    }

    fn overlays(&self, _cx: &ToolContext) -> Vec<Overlay> {
        match &self.drag {
            Drag::Marquee { start, cur } => vec![Overlay::Marquee(Rect::from_points(*start, *cur))],
            Drag::Move { .. } => self.guides.clone(),
            _ => vec![],
        }
    }

    fn cursor(&self, cx: &ToolContext, p: Point, _m: Mods) -> Cursor {
        if self.direct {
            return Cursor::ArrowHollow;
        }
        match self.drag {
            Drag::Move { .. } => return Cursor::Move,
            Drag::Resize { handle, .. } => return handle_cursor(handle),
            Drag::Rotate { .. } => return Cursor::Rotate,
            _ => {}
        }
        match handle_at(cx, p) {
            Some(h) => handle_cursor(h),
            None if rotate_zone(cx, p).is_some() => Cursor::Rotate,
            None => Cursor::Arrow,
        }
    }

    fn busy(&self) -> bool {
        !matches!(self.drag, Drag::None)
    }
}

fn handle_cursor(h: usize) -> Cursor {
    match h {
        0 | 4 => Cursor::ResizeNwSe,
        2 | 6 => Cursor::ResizeNeSw,
        1 | 5 => Cursor::ResizeV,
        _ => Cursor::ResizeH,
    }
}
