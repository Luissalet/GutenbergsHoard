// Modified for Gutenberg: detached engine, own document and product identity.
use gutenberg_compose::Cache;
use gutenberg_doc::build::NewDocument;
use gutenberg_doc::{Document, ParaFormat, Selection, SpreadRef};
use gutenberg_geom::Rect;

use super::*;

fn ctx<'a>(d: &'a Document, s: &'a Selection, c: &'a Cache, l: &'a CanvasLayout) -> ToolContext<'a> {
    ToolContext { doc: d, selection: s, cache: c, layout: l, zoom: 1.0, layer: d.default_layer(), snap: false }
}

#[test]
fn frame_tool_drag_emits_begin_preview_commit() {
    let d = Document::new(&NewDocument::default());
    let (s, c, l) = (Selection::default(), Cache::new(), CanvasLayout::new(&d, false));
    let cx = ctx(&d, &s, &c, &l);
    let mut t = create("rectangleFrame");
    assert!(t.pointer(&cx, &PointerEvent::new(PointerKind::Down, 10.0, 10.0)).is_empty());
    let a = t.pointer(&cx, &PointerEvent::new(PointerKind::Drag, 110.0, 60.0));
    assert!(matches!(&a[0], Action::Begin(_)));
    match &a[1] {
        Action::Preview(cmd, p) => {
            assert_eq!(cmd, "frame.create");
            assert_eq!(p["rect"], serde_json::json!([10.0, 10.0, 110.0, 60.0]));
            assert_eq!(p["content"], "graphic");
        }
        other => panic!("{other:?}"),
    }
    assert_eq!(t.pointer(&cx, &PointerEvent::new(PointerKind::Up, 110.0, 60.0)), vec![Action::Commit]);
}

#[test]
fn selection_click_and_marquee() {
    let mut d = Document::new(&NewDocument::default());
    let lid = d.default_layer();
    let (fid, _) = d.add_text_frame(SpreadRef::Doc(0), Rect::new(100.0, 100.0, 200.0, 200.0), lid, "x", ParaFormat::default()).unwrap();
    let (s, c, l) = (Selection::default(), Cache::new(), CanvasLayout::new(&d, false));
    let cx = ctx(&d, &s, &c, &l);
    let mut t = create("selection");
    let a = t.pointer(&cx, &PointerEvent::new(PointerKind::Down, 150.0, 150.0));
    assert_eq!(a, vec![Action::Exec("selection.set".into(), serde_json::json!({"ids": [fid.0], "content": false}))]);
    t.pointer(&cx, &PointerEvent::new(PointerKind::Up, 150.0, 150.0));
    // Marquee from empty space.
    t.pointer(&cx, &PointerEvent::new(PointerKind::Down, 20.0, 20.0));
    t.pointer(&cx, &PointerEvent::new(PointerKind::Drag, 300.0, 300.0));
    let a = t.pointer(&cx, &PointerEvent::new(PointerKind::Up, 300.0, 300.0));
    assert_eq!(a, vec![Action::Exec("selection.set".into(), serde_json::json!({"ids": [fid.0], "add": false}))]);
}

#[test]
fn resize_rect_modifiers() {
    let r = Rect::new(0.0, 0.0, 100.0, 50.0);
    assert_eq!(select::resize_rect(r, 4, gutenberg_geom::Point::new(200.0, 80.0), Mods::default()), Rect::new(0.0, 0.0, 200.0, 80.0));
    let p = select::resize_rect(r, 4, gutenberg_geom::Point::new(200.0, 60.0), Mods { shift: true, ..Default::default() });
    assert_eq!(p, Rect::new(0.0, 0.0, 200.0, 100.0));
    let c = select::resize_rect(r, 3, gutenberg_geom::Point::new(150.0, 25.0), Mods { alt: true, ..Default::default() });
    assert_eq!(c, Rect::new(-50.0, 0.0, 150.0, 50.0));
}

#[test]
fn cmd_shift_click_overrides_parent_item() {
    let mut d = Document::new(&NewDocument::default());
    let lid = d.default_layer();
    // On the parent's right page, which shows behind document page 1 (a right page).
    let px = d.parents[0].pages.last().unwrap().x;
    let (pid, _) =
        d.add_text_frame(SpreadRef::Parent(0), Rect::new(px + 100.0, 100.0, px + 200.0, 200.0), lid, "folio", ParaFormat::default()).unwrap();
    let (s, c, l) = (Selection::default(), Cache::new(), CanvasLayout::new(&d, false));
    let cx = ctx(&d, &s, &c, &l);
    let off = l.xf(SpreadRef::Doc(0)).translation();
    let x = d.spreads[0].pages[0].x + 150.0 + off.x;
    let mut t = create("selection");
    // A plain click doesn't reach parent items.
    let a = t.pointer(&cx, &PointerEvent::new(PointerKind::Down, x, 150.0 + off.y));
    assert_eq!(a, vec![Action::Exec("selection.set".into(), serde_json::json!({"ids": []}))]);
    t.pointer(&cx, &PointerEvent::new(PointerKind::Up, x, 150.0 + off.y));
    let mut ev = PointerEvent::new(PointerKind::Down, x, 150.0 + off.y);
    ev.mods = Mods { cmd: true, shift: true, ..Default::default() };
    let a = t.pointer(&cx, &ev);
    assert_eq!(a, vec![Action::Exec("layout.overrideParentItems".into(), serde_json::json!({"page": 0, "ids": [pid.0]}))]);
}

#[test]
fn gradient_tool_drag_sets_the_vector() {
    let mut d = Document::new(&NewDocument::default());
    let lid = d.default_layer();
    let (fid, _) = d.add_text_frame(SpreadRef::Doc(0), Rect::new(100.0, 100.0, 300.0, 200.0), lid, "", ParaFormat::default()).unwrap();
    let (s, c, l) = (Selection::default(), Cache::new(), CanvasLayout::new(&d, false));
    let cx = ctx(&d, &s, &c, &l);
    let off = l.xf(SpreadRef::Doc(0)).translation();
    let mut t = create("gradientSwatch");
    assert_eq!(t.pointer(&cx, &PointerEvent::new(PointerKind::Down, 120.0 + off.x, 150.0 + off.y)), vec![Action::Begin("Gradient".into())]);
    // Shift snaps a slightly tilted drag to horizontal.
    let a = t.pointer(&cx, &PointerEvent::new(PointerKind::Drag, 220.0 + off.x, 153.0 + off.y).with_mods(Mods { shift: true, ..Default::default() }));
    match &a[0] {
        Action::Preview(cmd, p) => {
            assert_eq!(cmd, "object.gradient");
            assert_eq!(p["ids"], serde_json::json!([fid.0]));
            assert_eq!(p["from"], serde_json::json!([120.0, 150.0]));
            let to = p["to"].as_array().unwrap();
            assert!((to[1].as_f64().unwrap() - 150.0).abs() < 1e-9, "{to:?}");
        }
        other => panic!("{other:?}"),
    }
    assert_eq!(t.pointer(&cx, &PointerEvent::new(PointerKind::Up, 220.0 + off.x, 153.0 + off.y)), vec![Action::Commit]);
}

#[test]
fn anchor_tools_emit_path_commands() {
    let mut d = Document::new(&NewDocument::default());
    let lid = d.default_layer();
    let (fid, _) = d.add_text_frame(SpreadRef::Doc(0), Rect::new(100.0, 100.0, 200.0, 200.0), lid, "", ParaFormat::default()).unwrap();
    let (s, c, l) = (Selection::items(vec![fid]), Cache::new(), CanvasLayout::new(&d, false));
    let cx = ctx(&d, &s, &c, &l);
    let off = l.xf(SpreadRef::Doc(0)).translation();
    let at = |x: f64, y: f64| (x + off.x, y + off.y);
    let ev = |k, (x, y): (f64, f64)| PointerEvent::new(k, x, y);
    let mut add = create("addAnchor");
    match &add.pointer(&cx, &ev(PointerKind::Down, at(150.0, 101.0)))[..] {
        [Action::Exec(cmd, p)] => {
            assert_eq!(cmd, "path.addAnchor");
            assert_eq!(p["at"], serde_json::json!([150.0, 101.0]));
        }
        other => panic!("{other:?}"),
    }
    assert!(add.pointer(&cx, &ev(PointerKind::Down, at(150.0, 150.0))).is_empty(), "inside, away from the edge");
    let mut del = create("deleteAnchor");
    assert_eq!(
        del.pointer(&cx, &ev(PointerKind::Down, at(200.0, 100.0))),
        vec![Action::Exec("path.deleteAnchor".into(), serde_json::json!({"id": fid.0, "subpath": 0, "anchor": 1}))]
    );
    // Convert: click toggles, drag pulls out handles.
    let mut conv = create("convertDirection");
    conv.pointer(&cx, &ev(PointerKind::Down, at(100.0, 100.0)));
    assert_eq!(
        conv.pointer(&cx, &ev(PointerKind::Up, at(100.0, 100.0))),
        vec![Action::Exec("path.convertAnchor".into(), serde_json::json!({"id": fid.0, "subpath": 0, "anchor": 0}))]
    );
    conv.pointer(&cx, &ev(PointerKind::Down, at(100.0, 100.0)));
    let a = conv.pointer(&cx, &ev(PointerKind::Drag, at(120.0, 90.0)));
    assert_eq!(a[0], Action::Begin("Convert Direction Point".into()));
    assert!(matches!(&a[1], Action::Preview(c, p) if c == "path.convertAnchor" && p["to"] == serde_json::json!([120.0, 90.0])));
    assert_eq!(conv.pointer(&cx, &ev(PointerKind::Up, at(120.0, 90.0))), vec![Action::Commit]);
}

#[test]
fn scissors_tool_cuts_where_clicked() {
    let mut d = Document::new(&NewDocument::default());
    let lid = d.default_layer();
    let (fid, _) = d.add_text_frame(SpreadRef::Doc(0), Rect::new(100.0, 100.0, 200.0, 200.0), lid, "", ParaFormat::default()).unwrap();
    let (s, c, l) = (Selection::items(vec![fid]), Cache::new(), CanvasLayout::new(&d, false));
    let cx = ctx(&d, &s, &c, &l);
    let off = l.xf(SpreadRef::Doc(0)).translation();
    let mut t = create("scissors");
    let a = t.pointer(&cx, &PointerEvent::new(PointerKind::Down, 150.0 + off.x, 100.0 + off.y));
    assert_eq!(a, vec![Action::Exec("path.split".into(), serde_json::json!({"id": fid.0, "at": [150.0, 100.0]}))]);
}

#[test]
fn pencil_draws_a_smooth_path() {
    let d = Document::new(&NewDocument::default());
    let (s, c, l) = (Selection::default(), Cache::new(), CanvasLayout::new(&d, false));
    let cx = ctx(&d, &s, &c, &l);
    let off = l.xf(SpreadRef::Doc(0)).translation();
    let mut t = create("pencil");
    t.pointer(&cx, &PointerEvent::new(PointerKind::Down, 100.0 + off.x, 100.0 + off.y));
    for i in 1..=90 {
        let a = (i as f64 * 2.0).to_radians();
        t.pointer(&cx, &PointerEvent::new(PointerKind::Drag, 100.0 + 50.0 * a.sin() + off.x, 100.0 + 50.0 * (1.0 - a.cos()) + off.y));
    }
    assert!(t.busy());
    let a = t.pointer(&cx, &PointerEvent::new(PointerKind::Up, 150.0 + off.x, 150.0 + off.y));
    match &a[..] {
        [Action::Exec(cmd, p)] => {
            assert_eq!(cmd, "path.create");
            let n = p["anchors"].as_array().unwrap().len();
            assert!((3..30).contains(&n), "{n} anchors");
            assert_eq!(p["anchors"][0]["p"], serde_json::json!([100.0, 100.0]));
        }
        other => panic!("{other:?}"),
    }
}

#[test]
fn zoom_tool_click_and_scrub() {
    let d = Document::new(&NewDocument::default());
    let (s, c, l) = (Selection::default(), Cache::new(), CanvasLayout::new(&d, false));
    let cx = ctx(&d, &s, &c, &l);
    let mut t = create("zoom");
    t.pointer(&cx, &PointerEvent::new(PointerKind::Down, 100.0, 100.0));
    assert_eq!(
        t.pointer(&cx, &PointerEvent::new(PointerKind::Up, 100.0, 100.0)),
        vec![Action::View(serde_json::json!({"zoomAt": [100.0, 100.0], "factor": 2.0}))]
    );
    // Dragging 150 px right zooms in by e, anchored at the press point; no click zoom after.
    t.pointer(&cx, &PointerEvent::new(PointerKind::Down, 100.0, 100.0));
    match &t.pointer(&cx, &PointerEvent::new(PointerKind::Drag, 250.0, 100.0))[..] {
        [Action::View(v)] => {
            assert_eq!(v["zoomAt"], serde_json::json!([100.0, 100.0]));
            assert!((v["factor"].as_f64().unwrap() - std::f64::consts::E).abs() < 1e-9);
        }
        other => panic!("{other:?}"),
    }
    assert!(t.pointer(&cx, &PointerEvent::new(PointerKind::Up, 250.0, 100.0)).is_empty());
}

#[test]
fn hand_tool_alt_press_power_zooms() {
    let d = Document::new(&NewDocument::default());
    let (s, c, l) = (Selection::default(), Cache::new(), CanvasLayout::new(&d, false));
    let cx = ctx(&d, &s, &c, &l);
    let mut t = create("hand");
    let alt = Mods { alt: true, ..Default::default() };
    let phase = |a: Vec<Action>| match &a[..] {
        [Action::View(v)] => v["powerZoom"].as_str().unwrap_or("").to_string(),
        other => panic!("{other:?}"),
    };
    assert_eq!(phase(t.pointer(&cx, &PointerEvent::new(PointerKind::Down, 10.0, 10.0).with_mods(alt))), "start");
    assert_eq!(phase(t.pointer(&cx, &PointerEvent::new(PointerKind::Drag, 50.0, 60.0))), "move");
    assert_eq!(phase(t.pointer(&cx, &PointerEvent::new(PointerKind::Up, 50.0, 60.0))), "end");
    // A plain press pans as before.
    t.pointer(&cx, &PointerEvent::new(PointerKind::Down, 10.0, 10.0));
    assert!(t.pointer(&cx, &PointerEvent::new(PointerKind::Up, 10.0, 10.0)).is_empty());
}

#[test]
fn page_tool_opens_page_size() {
    let d = Document::new(&NewDocument::default());
    let (s, c, l) = (Selection::default(), Cache::new(), CanvasLayout::new(&d, false));
    let cx = ctx(&d, &s, &c, &l);
    let off = l.xf(SpreadRef::Doc(0)).translation();
    let mut t = create("page");
    let a = t.pointer(&cx, &PointerEvent::new(PointerKind::Up, 200.0 + off.x + d.spreads[0].pages[0].x, 200.0 + off.y));
    assert_eq!(a, vec![Action::Dialog("cmd:layout.pageSize".into(), serde_json::json!({"pages": [1], "width": 612.0, "height": 792.0}))]);
}

#[test]
fn type_on_path_tool_targets_paths() {
    let mut d = Document::new(&NewDocument::default());
    let lid = d.default_layer();
    let id = gutenberg_doc::ItemId(d.alloc());
    let mut it = gutenberg_doc::Item::new(
        id,
        lid,
        gutenberg_doc::Shape::GraphicLine,
        gutenberg_geom::shapes::line(gutenberg_geom::Point::new(100.0, 100.0), gutenberg_geom::Point::new(300.0, 100.0)),
    );
    it.stroke = gutenberg_doc::Stroke::default();
    d.insert_item(SpreadRef::Doc(0), it, None).unwrap();
    let (s, c, l) = (Selection::default(), Cache::new(), CanvasLayout::new(&d, false));
    let cx = ctx(&d, &s, &c, &l);
    let off = l.xf(SpreadRef::Doc(0)).translation();
    let mut t = create("typeOnPath");
    let a = t.pointer(&cx, &PointerEvent::new(PointerKind::Up, 200.0 + off.x, 100.0 + off.y));
    assert_eq!(a, vec![Action::Exec("type.onPath".into(), serde_json::json!({"id": id.0})), Action::SwitchTool("type".into())]);
}

#[test]
fn vertical_type_tool_draws_vertical_frames() {
    let d = Document::new(&NewDocument::default());
    let (s, c, l) = (Selection::default(), Cache::new(), CanvasLayout::new(&d, false));
    let cx = ctx(&d, &s, &c, &l);
    let mut t = create("verticalType");
    assert_eq!(t.id(), "verticalType");
    t.pointer(&cx, &PointerEvent::new(PointerKind::Down, 100.0, 100.0));
    let a = t.pointer(&cx, &PointerEvent::new(PointerKind::Drag, 200.0, 300.0));
    let p = a.iter().find_map(|x| match x {
        Action::Preview(id, p) if id == "frame.create" => Some(p.clone()),
        _ => None,
    });
    assert_eq!(p.unwrap()["vertical"], true);
}

#[test]
fn turned_spread_maps_points_both_ways() {
    let mut d = Document::new(&NewDocument::default());
    std::sync::Arc::make_mut(&mut d.spreads[0]).pages[0].view_rotation = 1;
    let l = CanvasLayout::new(&d, false);
    let slot = l.slots[0];
    let b = d.spreads[0].bounds();
    assert!((slot.bounds.width() - b.height()).abs() < 1e-6);
    let p = gutenberg_geom::Point::new(b.x0 + 10.0, b.y0 + 20.0);
    let c = slot.to_canvas(p);
    let back = slot.to_spread(c);
    assert!((back - p).hypot() < 1e-9);
    // A quarter turn clockwise: the spread's top-left lands at the canvas top-right.
    assert!((c.x - (slot.bounds.x1 - 20.0)).abs() < 1e-6 && (c.y - (slot.bounds.y0 + 10.0)).abs() < 1e-6, "{c:?} {:?}", slot.bounds);
    let (sr, sp) = l.spread_at(c).unwrap();
    assert_eq!(sr, SpreadRef::Doc(0));
    assert!((sp - p).hypot() < 1e-9);
    // A canvas drag rightwards is a drag down the spread.
    let dv = slot.delta_to_spread(gutenberg_geom::Vec2::new(10.0, 0.0));
    assert!(dv.x.abs() < 1e-9 && (dv.y + 10.0).abs() < 1e-9 || (dv.y - 10.0).abs() < 1e-9, "{dv:?}");
}
