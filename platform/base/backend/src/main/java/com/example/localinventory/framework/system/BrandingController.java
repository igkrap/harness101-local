package com.example.localinventory.framework.system;

import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.concurrent.TimeUnit;
import org.springframework.http.CacheControl;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import java.util.Map;
import java.util.Set;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/** System name, logo, favicon and theme. Readable before sign-in (the login page shows them). */
@RestController
public class BrandingController {
    private static final Set<String> KEYS = Set.of("system_name", "logo", "favicon", "theme_color", "theme_mode", "theme_style", "duplicate_login",
            "password_min_length", "password_require_mix", "password_require_special",
            // what a printed form says about the company itself
            "company_name", "company_ceo", "company_biz_no", "company_address", "company_phone");
    private static final String LOGIN_BACKGROUND = "login_background";
    private static final int MAX_BACKGROUND = 7_000_000;  // characters of a data: URL (about 5MB of image)
    private static final int MAX_IMAGE = 300_000;  // characters of a data: URL (about 220KB of image)
    private final JdbcTemplate jdbc;
    public BrandingController(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    @GetMapping("/api/auth/branding")
    public Map<String, String> branding() {
        Map<String, String> values = new LinkedHashMap<>();
        jdbc.query("SELECT setting_key, setting_value FROM sys_settings", row -> {
            if (KEYS.contains(row.getString(1))) values.put(camel(row.getString(1)), row.getString(2));
        });
        // The login background can be megabytes (a GIF), so only its version travels here; the image has its own URL.
        List<String> background = jdbc.queryForList("SELECT setting_value FROM sys_settings WHERE setting_key = ?", String.class, LOGIN_BACKGROUND);
        String image = background.isEmpty() ? "" : background.get(0);
        values.put("loginBackground", image.isEmpty() ? "" : Integer.toHexString(image.hashCode()) + Integer.toHexString(image.length()));
        return values;
    }

    /** The login page background image (public: it is shown before sign-in). */
    @GetMapping("/api/auth/branding/login-background")
    public ResponseEntity<byte[]> loginBackground() {
        List<String> stored = jdbc.queryForList("SELECT setting_value FROM sys_settings WHERE setting_key = ?", String.class, LOGIN_BACKGROUND);
        if (stored.isEmpty() || stored.get(0).isEmpty()) return ResponseEntity.notFound().build();
        String value = stored.get(0);
        int comma = value.indexOf(',');
        String type = value.substring("data:".length(), value.indexOf(';'));
        return ResponseEntity.ok().contentType(MediaType.parseMediaType(type)).cacheControl(CacheControl.maxAge(30, TimeUnit.DAYS))
                .body(Base64.getDecoder().decode(value.substring(comma + 1)));
    }

    /** image: a png/jpeg/webp/gif data: URL (about 5MB at most), or empty to remove the background. */
    @PutMapping("/api/system/settings/login-background")
    public Map<String, String> saveLoginBackground(@RequestBody Map<String, String> body) {
        String value = body.get("image") == null ? "" : body.get("image").trim();
        if (!value.isEmpty() && (value.length() > MAX_BACKGROUND || !value.matches("data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+")))
            throw bad("the login background must be a png/jpeg/webp/gif image up to about 5MB");
        jdbc.update("INSERT INTO sys_settings (setting_key, setting_value) VALUES (?, ?) ON CONFLICT (setting_key) DO UPDATE SET setting_value = EXCLUDED.setting_value", LOGIN_BACKGROUND, value);
        return branding();
    }

    @PutMapping("/api/system/settings")
    public Map<String, String> save(@RequestBody Map<String, String> body) {
        for (Map.Entry<String, String> entry : body.entrySet()) {
            String key = snake(entry.getKey());
            String value = entry.getValue() == null ? "" : entry.getValue().trim();
            if (!KEYS.contains(key)) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "unknown setting: " + entry.getKey());
            switch (key) {
                case "system_name" -> { if (value.isEmpty() || value.length() > 60) throw bad("systemName must be 1-60 characters"); }
                case "theme_color" -> { if (!value.matches("#[0-9a-fA-F]{6}")) throw bad("themeColor must be a #rrggbb colour"); }
                case "password_min_length" -> { if (!value.matches("\\d{1,2}") || Integer.parseInt(value) < 4 || Integer.parseInt(value) > 64) throw bad("passwordMinLength must be 4-64"); }
                case "password_require_mix", "password_require_special" -> { if (!value.equals("true") && !value.equals("false")) throw bad(entry.getKey() + " must be true or false"); }
                case "duplicate_login" -> { if (!value.equals("block") && !value.equals("allow")) throw bad("duplicateLogin must be block or allow"); }
                case "theme_style" -> { if (!Set.of("plain", "tint", "solid").contains(value)) throw bad("themeStyle must be plain, tint or solid"); }
                case "company_name", "company_ceo", "company_biz_no", "company_address", "company_phone" -> { if (value.length() > 200 || value.chars().anyMatch(letter -> letter < 32)) throw bad(entry.getKey() + " must be plain text up to 200 characters"); }
                case "theme_mode" -> { if (!value.equals("light") && !value.equals("dark")) throw bad("themeMode must be light or dark"); }
                default -> { if (!value.isEmpty() && (!value.matches("data:image/(png|jpeg|webp|svg\\+xml|x-icon|vnd\\.microsoft\\.icon);base64,[A-Za-z0-9+/=]+") || value.length() > MAX_IMAGE))
                    throw bad(entry.getKey() + " must be a png/jpeg/webp/svg/ico image up to about 220KB"); }
            }
            jdbc.update("INSERT INTO sys_settings (setting_key, setting_value) VALUES (?, ?) ON CONFLICT (setting_key) DO UPDATE SET setting_value = EXCLUDED.setting_value", key, value);
        }
        return branding();
    }

    private static ResponseStatusException bad(String message) { return new ResponseStatusException(HttpStatus.BAD_REQUEST, message); }
    private static String camel(String key) {
        StringBuilder out = new StringBuilder();
        boolean upper = false;
        for (char c : key.toCharArray()) { if (c == '_') upper = true; else { out.append(upper ? Character.toUpperCase(c) : c); upper = false; } }
        return out.toString();
    }
    private static String snake(String key) { return key.replaceAll("([A-Z])", "_$1").toLowerCase(); }
}
