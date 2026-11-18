package com.example.localinventory.framework.system;

import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/** The signed-in user's own account: name, e-mail and password. */
@RestController
public class AccountController {
    private final JdbcTemplate jdbc;
    private final PasswordEncoder encoder;
    private final PasswordPolicy policy;
    private final AccessLog log;
    public AccountController(JdbcTemplate jdbc, PasswordEncoder encoder, PasswordPolicy policy, AccessLog log) {
        this.jdbc = jdbc; this.encoder = encoder; this.policy = policy; this.log = log;
    }

    public record Profile(String displayName, String email) {}
    public record PasswordChange(String currentPassword, String newPassword) {}

    /** Shown on the sign-up and password forms (public). */
    @GetMapping("/api/auth/password-policy")
    public PasswordPolicy.Rules passwordPolicy() { return policy.rules(); }

    @GetMapping("/api/auth/me")
    public Map<String, Object> me(Authentication authentication) {
        return jdbc.queryForMap("SELECT username, display_name AS \"displayName\", COALESCE(email, '') AS email, password_changed_at AS \"passwordChangedAt\" FROM workspace_users WHERE username = ?",
                authentication.getName());
    }

    @PutMapping("/api/auth/me")
    public Map<String, Object> update(@RequestBody Profile profile, Authentication authentication) {
        String name = profile.displayName() == null ? "" : profile.displayName().trim();
        String email = profile.email() == null ? "" : profile.email().trim();
        if (name.isEmpty() || name.length() > 200) throw bad("이름을 입력하세요.");
        if (!email.isEmpty() && (!email.matches("[^@\\s]+@[^@\\s]+\\.[^@\\s]+") || email.length() > 200)) throw bad("이메일 형식이 올바르지 않습니다.");
        jdbc.update("UPDATE workspace_users SET display_name = ?, email = NULLIF(?, '') WHERE username = ?", name, email, authentication.getName());
        return me(authentication);
    }

    @PostMapping("/api/auth/me/password")
    public Map<String, Object> changePassword(@RequestBody PasswordChange change, Authentication authentication) {
        String user = authentication.getName();
        String hash = jdbc.queryForObject("SELECT password_hash FROM workspace_users WHERE username = ?", String.class, user);
        if (change.currentPassword() == null || !encoder.matches(change.currentPassword(), hash)) throw bad("현재 비밀번호가 올바르지 않습니다.");
        policy.check(change.newPassword());
        if (encoder.matches(change.newPassword(), hash)) throw bad("새 비밀번호가 현재 비밀번호와 같습니다.");
        jdbc.update("UPDATE workspace_users SET password_hash = ?, password_changed_at = CURRENT_TIMESTAMP WHERE username = ?", encoder.encode(change.newPassword()), user);
        log.record(user, "PASSWORD_CHANGED", null, "");
        return Map.of("changed", true);
    }

    private static ResponseStatusException bad(String message) { return new ResponseStatusException(HttpStatus.BAD_REQUEST, message); }
}
