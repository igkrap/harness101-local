package com.example.localinventory.framework.system;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Set;
import java.util.stream.Collectors;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.GrantedAuthority;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

/** Server-side program permission: hiding a button is not enough, the API refuses what the roles do not grant. */
public class ProgramAccessFilter extends OncePerRequestFilter {
    private final SystemAccessService access;
    public ProgramAccessFilter(SystemAccessService access) { this.access = access; }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        return !path.startsWith("/api/") || path.startsWith("/api/auth/") || path.startsWith("/api/system/");
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain) throws ServletException, IOException {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication != null && authentication.isAuthenticated() && !(authentication instanceof AnonymousAuthenticationToken)) {
            Set<String> authorities = authentication.getAuthorities().stream().map(GrantedAuthority::getAuthority).collect(Collectors.toSet());
            if (!access.isAdmin(authentication.getName(), authorities)
                    && !access.allowed(authentication.getName(), request.getMethod(), request.getRequestURI())) {
                response.setStatus(403);
                response.setContentType("application/json");
                response.getWriter().write("{\"error\":\"PROGRAM_FORBIDDEN\"}");
                return;
            }
        }
        chain.doFilter(request, response);
    }
}
