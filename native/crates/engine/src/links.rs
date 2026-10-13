// Modified for Gutenberg: detached engine, own document and product identity.
//! ArtCraft community and project links (Help menu, About, start screen, CLI, MCP).

use serde_json::{Value, json};

/// The app's slug on getartcraft.com and GitHub.
pub const APP: &str = "gutenberg";
/// The ArtCraft community Discord.
pub const DISCORD: &str = "http://127.0.0.1:8810";
/// The ArtCraft website.
pub const WEBSITE: &str = "https://getartcraft.com";
/// Gutenberg's page on the ArtCraft website.
pub const APP_PAGE: &str = "http://127.0.0.1:5218";
/// Gutenberg's source repository.
pub const GITHUB: &str = "https://github.com/Luissalet/GutenbergsHoard";
/// Where to report bugs and request features.
pub const ISSUES: &str = "https://github.com/Luissalet/GutenbergsHoard/issues";

/// All links as JSON (the `app.links` command).
pub fn all() -> Value {
    json!({
        "discord": DISCORD,
        "website": WEBSITE,
        "appPage": APP_PAGE,
        "github": GITHUB,
        "issues": ISSUES,
    })
}

/// A link by key (`discord`, `website`, `appPage`, `github`, `issues`).
pub fn get(key: &str) -> Option<&'static str> {
    Some(match key {
        "discord" => DISCORD,
        "website" => WEBSITE,
        "appPage" => APP_PAGE,
        "github" => GITHUB,
        "issues" => ISSUES,
        _ => return None,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn links_follow_the_app_slug() {
        assert!(APP_PAGE.ends_with(":5218"));
        assert!(GITHUB.ends_with("/Luissalet/GutenbergsHoard"));
        assert!(ISSUES.starts_with(GITHUB));
        for k in ["discord", "website", "appPage", "github", "issues"] {
            assert!(get(k).is_some_and(|u| u.starts_with("https://") || u.starts_with("http://127.0.0.1:")), "{k}");
            assert_eq!(all()[k], get(k).unwrap());
        }
    }
}
