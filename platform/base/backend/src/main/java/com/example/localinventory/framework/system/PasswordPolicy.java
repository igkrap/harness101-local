package com.example.localinventory.framework.system;

import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

/** The password rules set in the system settings; every place that sets a password checks them here. */
@Component
public class PasswordPolicy {
    private final JdbcTemplate jdbc;
    public PasswordPolicy(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public record Rules(int minLength, boolean requireMix, boolean requireSpecial, String description) {}

    public Rules rules() {
        Map<String, String> values = new LinkedHashMap<>();
        jdbc.query("SELECT setting_key, setting_value FROM sys_settings WHERE setting_key LIKE 'password_%'", row -> { values.put(row.getString(1), row.getString(2)); });
        int min;
        try { min = Math.max(4, Math.min(64, Integer.parseInt(values.getOrDefault("password_min_length", "8")))); } catch (NumberFormatException e) { min = 8; }
        boolean mix = "true".equals(values.get("password_require_mix")), special = "true".equals(values.get("password_require_special"));
        String text = min + "자 이상" + (mix ? ", 영문과 숫자 포함" : "") + (special ? ", 특수문자 포함" : "");
        return new Rules(min, mix, special, text);
    }

    /** Throws 400 with a plain message when the password breaks a rule. */
    public void check(String password) {
        Rules rules = rules();
        String value = password == null ? "" : password;
        boolean ok = value.length() >= rules.minLength() && value.length() <= 100
                && (!rules.requireMix() || (value.matches(".*[A-Za-z].*") && value.matches(".*[0-9].*")))
                && (!rules.requireSpecial() || value.matches(".*[^A-Za-z0-9].*"));
        if (!ok) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "비밀번호는 " + rules.description() + "이어야 합니다.");
    }
}
