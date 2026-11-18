package com.example.localinventory.framework.system;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.context.event.EventListener;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.authentication.event.AbstractAuthenticationFailureEvent;
import org.springframework.security.authentication.event.InteractiveAuthenticationSuccessEvent;
import org.springframework.security.authentication.event.LogoutSuccessEvent;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

/** Writes the access log: sign-ins, failed attempts, sign-outs, replaced sessions, opened programs. Never fails a request. */
@Component
public class AccessLog {
    private final JdbcTemplate jdbc;
    public AccessLog(JdbcTemplate jdbc) { this.jdbc = jdbc; }

    public void record(String username, String event, String programCode, String detail) {
        try {
            jdbc.update("INSERT INTO sys_access_logs (username, event, program_code, ip, detail) VALUES (?, ?, ?, ?, ?)",
                    cut(username, 100), event, programCode == null ? null : cut(programCode, 100), cut(ip(), 64), cut(detail, 300));
        } catch (RuntimeException ignored) { /* a log line must not break sign-in or a screen */ }
    }

    @EventListener
    public void signedIn(InteractiveAuthenticationSuccessEvent event) { record(event.getAuthentication().getName(), "LOGIN", null, ""); }

    @EventListener
    public void failed(AbstractAuthenticationFailureEvent event) {
        record(event.getAuthentication().getName(), "LOGIN_FAILED", null, event.getException().getClass().getSimpleName().replace("Exception", ""));
    }

    @EventListener
    public void signedOut(LogoutSuccessEvent event) { record(event.getAuthentication().getName(), "LOGOUT", null, ""); }

    private static String cut(String value, int max) { return value == null ? "" : value.length() > max ? value.substring(0, max) : value; }

    private static String ip() {
        if (!(RequestContextHolder.getRequestAttributes() instanceof ServletRequestAttributes attributes)) return "";
        HttpServletRequest request = attributes.getRequest();
        String forwarded = request.getHeader("X-Forwarded-For");
        return forwarded != null && !forwarded.isBlank() ? forwarded.split(",")[0].trim() : request.getRemoteAddr();
    }
}
