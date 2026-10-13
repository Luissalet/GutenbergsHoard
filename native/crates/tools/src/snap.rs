// Modified for Gutenberg: detached engine, own document and product identity.
//! Snapping and smart guides: page edges and centres, margins, column guides, ruler guides and
//! other objects' edges/centres on the same spread. Returns the snap correction and the guide
//! lines to draw (canvas coordinates).

use gutenberg_doc::{ItemId, Orientation, SpreadRef};
use gutenberg_geom::{Point, Rect, Vec2};

use crate::{Overlay, ToolContext};

#[derive(Clone, Debug, Default)]
pub struct Snap {
    pub delta: Vec2,
    pub guides: Vec<Overlay>,
}

#[derive(Clone, Copy)]
struct Target {
    v: f64,
    /// Extent of the target along the other axis (for drawing the guide).
    lo: f64,
    hi: f64,
    smart: bool,
}

fn targets(cx: &ToolContext, sr: SpreadRef, exclude: &[ItemId]) -> (Vec<Target>, Vec<Target>) {
    let mut xs = Vec::new();
    let mut ys = Vec::new();
    let Some(sp) = cx.doc.spread(sr) else { return (xs, ys) };
    let push = |v: &mut Vec<Target>, val: f64, lo: f64, hi: f64, smart: bool| v.push(Target { v: val, lo, hi, smart });
    for p in &sp.pages {
        let b = p.bounds();
        let m = p.margin_rect();
        for x in [b.x0, b.center().x, b.x1, m.x0, m.x1] {
            push(&mut xs, x, b.y0, b.y1, false);
        }
        for y in [b.y0, b.center().y, b.y1, m.y0, m.y1] {
            push(&mut ys, y, b.x0, b.x1, false);
        }
        for c in p.column_rects() {
            push(&mut xs, c.x0, b.y0, b.y1, false);
            push(&mut xs, c.x1, b.y0, b.y1, false);
        }
        for g in &p.guides {
            match g.orientation {
                Orientation::Vertical => push(&mut xs, g.position, b.y0, b.y1, false),
                Orientation::Horizontal => push(&mut ys, g.position, b.x0, b.x1, false),
            }
        }
    }
    for it in &sp.items {
        if exclude.contains(&it.id) || it.hidden {
            continue;
        }
        let b = it.bounds();
        for x in [b.x0, b.center().x, b.x1] {
            push(&mut xs, x, b.y0, b.y1, true);
        }
        for y in [b.y0, b.center().y, b.y1] {
            push(&mut ys, y, b.x0, b.x1, true);
        }
    }
    (xs, ys)
}

fn best(cands: &[f64], targets: &[Target], tol: f64) -> Option<(f64, Target)> {
    let mut out: Option<(f64, Target)> = None;
    for &c in cands {
        for t in targets {
            let d = t.v - c;
            if d.abs() <= tol && out.is_none_or(|(od, _)| d.abs() < od.abs()) {
                out = Some((d, *t));
            }
        }
    }
    out
}

/// Snap a moving rect (spread coords). Edges and centre snap independently per axis.
pub fn snap_rect(cx: &ToolContext, sr: SpreadRef, r: Rect, exclude: &[ItemId]) -> Snap {
    let tol = cx.tol(5.0);
    let (xs, ys) = targets(cx, sr, exclude);
    let mut s = Snap::default();
    let xf = cx.layout.xf(sr);
    if let Some((d, t)) = best(&[r.x0, r.center().x, r.x1], &xs, tol) {
        s.delta.x = d;
        let lo = t.lo.min(r.y0) - 6.0;
        let hi = t.hi.max(r.y1) + 6.0;
        s.guides.push(guide(xf * Point::new(t.v, lo), xf * Point::new(t.v, hi), t.smart));
    }
    if let Some((d, t)) = best(&[r.y0, r.center().y, r.y1], &ys, tol) {
        s.delta.y = d;
        let lo = t.lo.min(r.x0) - 6.0;
        let hi = t.hi.max(r.x1) + 6.0;
        s.guides.push(guide(xf * Point::new(lo, t.v), xf * Point::new(hi, t.v), t.smart));
    }
    s
}

/// Snap a single point (drawing tools).
pub fn snap_point(cx: &ToolContext, sr: SpreadRef, p: Point) -> (Point, Vec<Overlay>) {
    let s = snap_rect(cx, sr, Rect::from_points(p, p), &[]);
    (p + s.delta, s.guides)
}

fn guide(a: Point, b: Point, smart: bool) -> Overlay {
    if smart { Overlay::Guide { a, b } } else { Overlay::Line { a, b, color: [255, 0, 255], dashed: false } }
}
