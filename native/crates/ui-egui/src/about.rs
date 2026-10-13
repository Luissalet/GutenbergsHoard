// Modified for Gutenberg: detached engine, own document and product identity.
//! Help › About Gutenberg: the splash with the ArtCraft mark, version, and community links
//! (Discord first and largest), plus the other ArtCraft apps.

use gutenberg_engine::links;
use egui::{Color32, Rect, Sense, Stroke, pos2, vec2};
use serde_json::json;

use crate::DesignApp;
use crate::theme::{Tokens, semibold};

/// Historical accent colour (from `docs/brand/artcraft-mark.svg`).
pub const BRAND: Color32 = Color32::from_rgb(0x4e, 0x7b, 0xfb);
/// Discord's brand colour, used for the "Join our Discord" buttons (colour only; no Discord artwork).
pub const DISCORD: Color32 = Color32::from_rgb(0x58, 0x65, 0xf2);

/// The other ArtCraft apps (app-page slug, name, what it is) — same list as the README.
pub const SIBLINGS: &[(&str, &str, &str)] = &[
    ("photocraft", "PhotoCraft", "image editing"),
    ("drawcraft", "VectorCraft", "vector illustration"),
    ("filmcraft", "FilmCraft", "video editing, color and sound"),
    ("lightcraft", "LightCraft", "photo library and raw development"),
    ("printcraft", "PrintCraft", "reading, organizing and protecting PDFs"),
    ("effectcraft", "EffectCraft", "motion graphics and visual effects"),
];

/// Paint this Hoard's existing artwork, cached once per egui context.
pub fn paint_mark(ui: &egui::Ui, rect: Rect, _color: Color32) {
    let ctx = ui.ctx();
    let key = egui::Id::new("gutenberg_hoard_icon");
    let tex: Option<egui::TextureHandle> = ctx.data(|d| d.get_temp(key));
    let tex = tex.unwrap_or_else(|| {
        let bytes = include_bytes!("../../../assets/app-icon/gutenberg-macos-512.png");
        let image = image::load_from_memory(bytes).expect("owned bundled Hoard icon").into_rgba8();
        let ci = egui::ColorImage::from_rgba_unmultiplied([image.width() as usize, image.height() as usize], image.as_raw());
        let texture = ctx.load_texture("gutenberg_hoard_icon", ci, egui::TextureOptions::LINEAR);
        ctx.data_mut(|d| d.insert_temp(key, texture.clone()));
        texture
    });
    ui.painter().image(tex.id(), rect, Rect::from_min_max(pos2(0.0, 0.0), pos2(1.0, 1.0)), Color32::WHITE);
}

/// A speech-bubble glyph (drawn in code) for Discord buttons.
pub fn paint_chat_icon(p: &egui::Painter, c: egui::Pos2, s: f32, color: Color32) {
    let body = Rect::from_center_size(c - vec2(0.0, s * 0.06), vec2(s, s * 0.72));
    p.rect_filled(body, s * 0.24, color);
    let tail = vec![
        pos2(body.left() + s * 0.22, body.bottom() - 1.0),
        pos2(body.left() + s * 0.12, body.bottom() + s * 0.24),
        pos2(body.left() + s * 0.44, body.bottom() - 1.0),
    ];
    p.add(egui::Shape::convex_polygon(tail, color, Stroke::NONE));
    let eye = s * 0.09;
    let bg = if color.r() as u32 + color.g() as u32 + color.b() as u32 > 380 { DISCORD } else { Color32::WHITE };
    p.circle_filled(body.center() - vec2(s * 0.18, 0.0), eye, bg);
    p.circle_filled(body.center() + vec2(s * 0.18, 0.0), eye, bg);
}

/// The big "Join our Discord" button. Returns true when clicked.
pub fn discord_button(ui: &mut egui::Ui, label: &str, size: egui::Vec2) -> bool {
    let (r, resp) = ui.allocate_exact_size(size, Sense::click());
    let resp = resp.on_hover_text(links::DISCORD).on_hover_cursor(egui::CursorIcon::PointingHand);
    let fill = if resp.hovered() { Color32::from_rgb(0x47, 0x52, 0xc4) } else { DISCORD };
    ui.painter().rect_filled(r, size.y / 2.0, fill);
    let icon = size.y * 0.5;
    let font = semibold((size.y * 0.42).max(11.0));
    let galley = ui.painter().layout_no_wrap(label.to_string(), font, Color32::WHITE);
    let total = icon + 8.0 + galley.size().x;
    let x0 = r.center().x - total / 2.0;
    paint_chat_icon(ui.painter(), pos2(x0 + icon / 2.0, r.center().y), icon, Color32::WHITE);
    ui.painter().galley(pos2(x0 + icon + 8.0, r.center().y - galley.size().y / 2.0), galley, Color32::WHITE);
    resp.clicked()
}

/// A text link that opens `url`. Returns true when clicked.
fn link(ui: &mut egui::Ui, text: &str, url: &str, color: Color32) -> bool {
    let resp = ui.add(egui::Label::new(egui::RichText::new(text).size(13.0).color(color).underline()).sense(Sense::click()));
    let resp = resp.on_hover_text(url).on_hover_cursor(egui::CursorIcon::PointingHand);
    resp.clicked()
}

pub fn show(app: &mut DesignApp, ctx: &egui::Context) {
    if !app.ui.about {
        return;
    }
    let t = Tokens::get(ctx);
    let mut open: Option<&'static str> = None;
    let resp = egui::Modal::new(egui::Id::new("about")).show(ctx, |ui| {
        ui.set_width(460.0);
        ui.vertical_centered(|ui| {
            ui.add_space(8.0);
            let (r, _) = ui.allocate_exact_size(vec2(72.0, 72.0), Sense::hover());
            paint_mark(ui, r, BRAND);
            ui.add_space(6.0);
            ui.label(egui::RichText::new("Gutenberg").font(semibold(26.0)).color(t.text_strong));
            ui.label(egui::RichText::new(format!("Version {}", env!("CARGO_PKG_VERSION"))).size(12.0).color(t.text_dim));
            ui.add_space(4.0);
            ui.label(egui::RichText::new("Editable page layout, stories, frames and PDF export.").size(13.0).color(t.text));
            ui.label(egui::RichText::new("Part of the Hoard family; source attribution is retained in native/NOTICE.").size(12.0).color(t.text_dim));
            ui.add_space(16.0);
            if discord_button(ui, "Open Hoard Hub", vec2(300.0, 40.0)) {
                open = Some("discord");
            }
            ui.add_space(4.0);
            ui.label(egui::RichText::new("Local family applications and coordination").size(11.0).color(t.text_dim));
            ui.add_space(14.0);
            ui.horizontal(|ui| {
                // Centre the row of links.
                let w = 330.0;
                ui.add_space(((ui.available_width() - w) / 2.0).max(0.0));
                for (text, key) in
                    [("Gutenberg page", "appPage"), ("GitHub", "github"), ("getartcraft.com", "website"), ("Report an issue", "issues")]
                {
                    if link(ui, text, links::get(key).unwrap_or_default(), t.accent) {
                        open = Some(key);
                    }
                    ui.add_space(6.0);
                }
            });
            ui.add_space(16.0);
            ui.separator();
            ui.add_space(6.0);
            ui.label(egui::RichText::new("Related creative sources").font(semibold(12.0)).color(t.text_strong));
            ui.add_space(4.0);
            ui.horizontal(|ui| {
                let pad = ui.spacing().button_padding.x * 2.0 + ui.spacing().item_spacing.x;
                let w: f32 = SIBLINGS
                    .iter()
                    .map(|(_, n, _)| ui.painter().layout_no_wrap(n.to_string(), egui::FontId::proportional(12.0), Color32::WHITE).size().x + pad)
                    .sum::<f32>()
                    - ui.spacing().item_spacing.x;
                ui.add_space(((ui.available_width() - w) / 2.0).max(0.0));
                for (slug, name, what) in SIBLINGS {
                    let url = format!("{}/apps/{slug}", links::WEBSITE);
                    let b =
                        ui.add(egui::Button::new(egui::RichText::new(*name).size(12.0)).corner_radius(10.0)).on_hover_text(format!("{what} — {url}"));
                    if b.clicked() {
                        app.ui.pending_urls.push(url);
                    }
                }
            });
            ui.add_space(12.0);
            ui.label(egui::RichText::new("Open source. No telemetry.").size(11.0).color(t.text_dim));
            ui.add_space(8.0);
            if ui.button("  Close  ").clicked() {
                app.ui.about = false;
            }
        });
    });
    if resp.should_close() {
        app.ui.about = false;
    }
    if let Some(k) = open {
        let _ = app.run(&format!("help.{k}"), json!({}));
    }
}
