package com.example.localinventory.framework.auth;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

@Entity
@Table(name = "workspace_users")
public class WorkspaceUser {
    @Id
    @Column(length = 100)
    private String username;
    @Column(name = "password_hash", nullable = false, length = 255)
    private String passwordHash;
    @Column(name = "display_name", nullable = false, length = 200)
    private String displayName;
    @Column(nullable = false, length = 1000)
    private String permissions;
    @Column(nullable = false)
    private boolean enabled;
    @Column(nullable = false, length = 20)
    private String status = "ACTIVE";

    protected WorkspaceUser() {}

    public WorkspaceUser(String username, String passwordHash, String displayName, String permissions) {
        this.username = username;
        this.passwordHash = passwordHash;
        this.displayName = displayName;
        this.permissions = permissions;
        this.enabled = true;
    }

    public String getUsername() { return username; }
    public String getPasswordHash() { return passwordHash; }
    public String getDisplayName() { return displayName; }
    public String getPermissions() { return permissions; }
    public boolean isEnabled() { return enabled; }
    public String getStatus() { return status; }
}
