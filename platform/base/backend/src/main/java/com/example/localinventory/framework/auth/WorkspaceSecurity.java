package com.example.localinventory.framework.auth;

import com.example.localinventory.framework.system.ProgramAccessFilter;
import com.example.localinventory.framework.system.SystemAccessService;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Arrays;
import java.util.stream.Stream;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configurers.AbstractHttpConfigurer;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.security.crypto.factory.PasswordEncoderFactories;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.csrf.CsrfException;

@Configuration
@EnableMethodSecurity
public class WorkspaceSecurity {
    @Bean
    PasswordEncoder workspacePasswordEncoder() {
        return PasswordEncoderFactories.createDelegatingPasswordEncoder();
    }

    @Bean
    UserDetailsService workspaceUsers(WorkspaceUserRepository users, SystemAccessService access) {
        return username -> {
            WorkspaceUser account = users.findById(username)
                    .orElseThrow(() -> new UsernameNotFoundException("Invalid credentials"));
            // Roles become ROLE_<code> authorities next to the legacy permission strings.
            String[] permissions = Stream.concat(
                    Arrays.stream(account.getPermissions().split(",")).map(String::trim).filter(value -> !value.isEmpty()),
                    access.rolesOf(username).stream().map(role -> "ROLE_" + role)).distinct().toArray(String[]::new);
            // Only approved accounts sign in (PENDING sign-ups wait for an administrator).
            return User.withUsername(account.getUsername()).password(account.getPasswordHash())
                    .authorities(permissions).disabled(!account.isEnabled() || !"ACTIVE".equals(account.getStatus())).build();
        };
    }

    @Bean
    ApplicationRunner workspaceBootstrap(WorkspaceUserRepository users, org.springframework.jdbc.core.JdbcTemplate jdbc,
            @Value("${workspace.auth.bootstrap.enabled:true}") boolean enabled,
            @Value("${WORKSPACE_ADMIN_USERNAME:admin}") String username,
            @Value("${WORKSPACE_ADMIN_PASSWORD_HASH:}") String givenHash,
            @Value("${WORKSPACE_ADMIN_PASSWORD:}") String firstPassword) {
        return args -> {
            if (!enabled || users.count() != 0) return;
            // A setup pack gives the first administrator's password in plain words (kept in the pack's own .env, used once, here);
            // it is stored only as a hash and is meant to be changed after the first sign-in.
            String passwordHash = givenHash.startsWith("{bcrypt}") || firstPassword.isBlank() ? givenHash
                    : "{bcrypt}" + new org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder().encode(firstPassword);
            if (!passwordHash.startsWith("{bcrypt}"))
                throw new IllegalStateException("Set WORKSPACE_ADMIN_PASSWORD (or WORKSPACE_ADMIN_PASSWORD_HASH, {bcrypt} encoded) for the first administrator");
            users.save(new WorkspaceUser(username, passwordHash, "관리자",
                    "workspace:admin,inventory:read,inventory:write,work-sites:read,work-sites:write"));
            jdbc.update("INSERT INTO sys_user_roles (username, role_code) VALUES (?, 'ADMIN') ON CONFLICT DO NOTHING", username);
        };
    }

    @Bean
    org.springframework.security.core.session.SessionRegistry workspaceSessionRegistry() {
        return new org.springframework.security.core.session.SessionRegistryImpl();
    }

    /** Lets the registry know when a session ends (logout, timeout). */
    @Bean
    static org.springframework.security.web.session.HttpSessionEventPublisher workspaceSessionEvents() {
        return new org.springframework.security.web.session.HttpSessionEventPublisher();
    }

    @Bean
    SecurityFilterChain workspaceSecurityFilterChain(HttpSecurity http, SystemAccessService access,
            org.springframework.security.core.session.SessionRegistry sessions, org.springframework.jdbc.core.JdbcTemplate jdbc,
            com.example.localinventory.framework.system.AccessLog accessLog) throws Exception {
        http.addFilterAfter(new ProgramAccessFilter(access), org.springframework.security.web.access.intercept.AuthorizationFilter.class);
        http.authorizeHttpRequests(authorize -> authorize
                // The async re-dispatch that ends a live event stream was already authorised when the stream opened.
                .dispatcherTypeMatchers(jakarta.servlet.DispatcherType.ASYNC, jakarta.servlet.DispatcherType.ERROR).permitAll()
                .requestMatchers(HttpMethod.GET, "/api/auth/session", "/api/auth/branding", "/api/auth/branding/login-background", "/api/auth/password-policy").permitAll()
                .requestMatchers("/api/auth/login", "/api/auth/signup", "/error").permitAll()
                .requestMatchers("/api/specs/**").hasAuthority("workspace:admin")
                .requestMatchers("/api/system/**").hasAnyAuthority("workspace:admin", "ROLE_ADMIN")
                .requestMatchers(HttpMethod.GET, "/api/inventory", "/api/inventory/**").hasAuthority("inventory:read")
                .requestMatchers("/api/inventory", "/api/inventory/**").hasAuthority("inventory:write")
                .requestMatchers(HttpMethod.GET, "/api/work-sites", "/api/work-sites/**").hasAuthority("work-sites:read")
                .requestMatchers("/api/work-sites", "/api/work-sites/**").hasAuthority("work-sites:write")
                .requestMatchers("/api/**").authenticated()
                // The built screens themselves (the page, its scripts and pictures), when this server is also the one that serves
                // them (an operating copy started with spring.web.resources.static-locations): they hold nothing private.
                .requestMatchers(HttpMethod.GET, "/", "/index.html", "/assets/**", "/favicon.ico", "/*.svg", "/*.png", "/*.ico", "/*.webmanifest").permitAll()
                .anyRequest().denyAll())
            .formLogin(login -> login.loginProcessingUrl("/api/auth/login")
                .successHandler((request, response, authentication) -> {
                    response.setContentType("application/json");
                    response.getWriter().write("{\"authenticated\":true}");
                })
                // A correct password on an account that is not ACTIVE (sign-up waiting for approval, rejected, locked) says so.
                .failureHandler((request, response, exception) -> error(response, 401,
                        exception instanceof org.springframework.security.authentication.DisabledException ? "ACCOUNT_NOT_ACTIVE" : "INVALID_CREDENTIALS")))
            .logout(logout -> logout.logoutUrl("/api/auth/logout").invalidateHttpSession(true)
                .deleteCookies("JSESSIONID")
                .logoutSuccessHandler((request, response, authentication) -> response.setStatus(204)))
            // One live sign-in per account: a new sign-in ends the earlier one, which is told why on its next request.
            // Administrators can allow duplicates in the system settings (duplicate_login = allow).
            .sessionManagement(session -> session.sessionFixation(fixation -> fixation.changeSessionId())
                .maximumSessions(1)
                .maximumSessions((org.springframework.security.web.authentication.session.SessionLimit) authentication -> duplicateLoginAllowed(jdbc) ? -1 : 1)
                .sessionRegistry(sessions)
                .expiredSessionStrategy(event -> {
                    Object principal = event.getSessionInformation().getPrincipal();
                    accessLog.record(principal instanceof org.springframework.security.core.userdetails.UserDetails user ? user.getUsername() : String.valueOf(principal), "SESSION_REPLACED", null, "");
                    error(event.getResponse(), 401, "SESSION_REPLACED");
                }))
            .requestCache(AbstractHttpConfigurer::disable)
            .httpBasic(AbstractHttpConfigurer::disable)
            .exceptionHandling(exceptions -> exceptions
                .authenticationEntryPoint((request, response, exception) -> error(response, 401, "AUTH_REQUIRED"))
                .accessDeniedHandler((request, response, exception) -> error(response, 403,
                        exception instanceof CsrfException ? "CSRF_REQUIRED" : "FORBIDDEN")));
        return http.build();
    }

    private static boolean duplicateLoginAllowed(org.springframework.jdbc.core.JdbcTemplate jdbc) {
        return jdbc.queryForList("SELECT setting_value FROM sys_settings WHERE setting_key = 'duplicate_login'", String.class).contains("allow");
    }

    private static void error(HttpServletResponse response, int status, String code) throws IOException {
        response.setStatus(status);
        response.setContentType("application/json");
        response.getWriter().write("{\"error\":\"" + code + "\"}");
    }
}
