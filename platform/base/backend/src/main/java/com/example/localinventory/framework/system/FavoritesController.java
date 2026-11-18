package com.example.localinventory.framework.system;

import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/** The signed-in user's own favourite programs (any user; a favourite never grants access). */
@RestController
public class FavoritesController {
    private static final int LIMIT = 50;
    private final JdbcTemplate jdbc;
    public FavoritesController(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    @GetMapping("/api/auth/favorites")
    public List<String> list(Authentication authentication) {
        return jdbc.queryForList("SELECT program_code FROM sys_user_favorites WHERE username = ? ORDER BY created_at, program_code",
                String.class, authentication.getName());
    }

    @PutMapping("/api/auth/favorites/{code}")
    public List<String> add(@PathVariable String code, Authentication authentication) {
        if (code.isBlank() || code.length() > 100) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "code must be 1-100 characters");
        String user = authentication.getName();
        Integer present = jdbc.queryForObject("SELECT COUNT(*) FROM sys_user_favorites WHERE username = ? AND program_code = ?", Integer.class, user, code);
        if (present == null || present == 0) {
            Integer count = jdbc.queryForObject("SELECT COUNT(*) FROM sys_user_favorites WHERE username = ?", Integer.class, user);
            if (count != null && count >= LIMIT) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "favorites are limited to " + LIMIT);
            jdbc.update("INSERT INTO sys_user_favorites (username, program_code) VALUES (?, ?)", user, code);
        }
        return list(authentication);
    }

    @DeleteMapping("/api/auth/favorites/{code}")
    public List<String> remove(@PathVariable String code, Authentication authentication) {
        jdbc.update("DELETE FROM sys_user_favorites WHERE username = ? AND program_code = ?", authentication.getName(), code);
        return list(authentication);
    }
}
