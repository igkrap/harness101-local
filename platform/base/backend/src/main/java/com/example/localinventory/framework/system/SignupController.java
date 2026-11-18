package com.example.localinventory.framework.system;

import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/** Sign-up: anyone may ask for an account; it stays PENDING (cannot sign in) until an administrator approves it. */
@RestController
public class SignupController {
    private final JdbcTemplate jdbc;
    private final PasswordEncoder encoder;
    private final PasswordPolicy policy;
    public SignupController(JdbcTemplate jdbc, PasswordEncoder encoder, PasswordPolicy policy) { this.jdbc = jdbc; this.encoder = encoder; this.policy = policy; }

    public record SignupRequest(String username, String password, String displayName, String email) {}

    @PostMapping("/api/auth/signup")
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> signup(@RequestBody SignupRequest request) {
        String username = request.username() == null ? "" : request.username().trim();
        String name = request.displayName() == null ? "" : request.displayName().trim();
        String email = request.email() == null ? "" : request.email().trim();
        String password = request.password() == null ? "" : request.password();
        if (!username.matches("[A-Za-z0-9][A-Za-z0-9._-]{2,49}")) throw bad("아이디는 3~50자의 영문·숫자·._- 이어야 합니다.");
        policy.check(password);
        if (name.isEmpty() || name.length() > 200) throw bad("이름을 입력하세요.");
        if (!email.isEmpty() && (!email.matches("[^@\\s]+@[^@\\s]+\\.[^@\\s]+") || email.length() > 200)) throw bad("이메일 형식이 올바르지 않습니다.");
        if (jdbc.queryForObject("SELECT COUNT(*) FROM workspace_users WHERE LOWER(username) = LOWER(?)", Integer.class, username) > 0)
            throw new ResponseStatusException(HttpStatus.CONFLICT, "이미 사용 중인 아이디입니다.");
        jdbc.update("INSERT INTO workspace_users (username, password_hash, display_name, permissions, enabled, status, email, requested_at) VALUES (?, ?, ?, '', TRUE, 'PENDING', NULLIF(?, ''), CURRENT_TIMESTAMP)",
                username, encoder.encode(password), name, email);
        return Map.of("username", username, "status", "PENDING");
    }

    private static ResponseStatusException bad(String message) { return new ResponseStatusException(HttpStatus.BAD_REQUEST, message); }
}
