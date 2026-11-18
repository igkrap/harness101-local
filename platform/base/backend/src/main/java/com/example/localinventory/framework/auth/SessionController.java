package com.example.localinventory.framework.auth;

import com.example.localinventory.framework.system.SystemAccessService;
import java.util.List;
import java.util.Map;
import org.springframework.security.authentication.AnonymousAuthenticationToken;
import org.springframework.security.core.Authentication;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class SessionController {
    private final WorkspaceUserRepository users;
    private final SystemAccessService access;
    public SessionController(WorkspaceUserRepository users, SystemAccessService access) { this.users = users; this.access = access; }

    /**
     * roles/admin: role-based access. menus: system > module > menu the roles may see.
     * programs: what the roles may do per program (absent for administrators, who may do everything).
     * unassigned: programs not yet placed in a menu (administrators only).
     */
    public record UserView(String username, String displayName, List<String> permissions, List<String> roles, boolean admin,
            List<SystemAccessService.SystemView> menus, Map<String, SystemAccessService.ProgramPermission> programs,
            List<SystemAccessService.MenuView> unassigned) {}
    public record CsrfView(String headerName, String token) {}
    public record SessionView(boolean authenticated, UserView user, CsrfView csrf) {}

    @GetMapping("/api/auth/session")
    public SessionView session(Authentication authentication, CsrfToken csrf) {
        boolean authenticated = authentication != null && authentication.isAuthenticated()
                && !(authentication instanceof AnonymousAuthenticationToken);
        UserView user = null;
        if (authenticated) {
            String name = authentication.getName();
            String displayName = users.findById(name).map(WorkspaceUser::getDisplayName).orElse(name);
            List<String> authorities = authentication.getAuthorities().stream().map(authority -> authority.getAuthority()).toList();
            boolean admin = access.isAdmin(name, authorities);
            user = new UserView(name, displayName, authorities, access.rolesOf(name), admin, access.menuTree(name, admin),
                    admin ? Map.of() : access.programPermissions(name), admin ? access.unassignedPrograms() : List.of());
        }
        return new SessionView(authenticated, user, new CsrfView(csrf.getHeaderName(), csrf.getToken()));
    }
}
