package com.example.localinventory;

import com.example.localinventory.framework.auth.WorkspaceUser;
import com.example.localinventory.framework.auth.WorkspaceUserRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.mock.web.MockHttpSession;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.web.csrf.CsrfToken;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.csrf;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.user;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@org.springframework.transaction.annotation.Transactional
class WorkspaceAuthenticationTest {
    @Autowired MockMvc mvc;
    @Autowired WorkspaceUserRepository users;
    @Autowired PasswordEncoder encoder;

    @BeforeEach
    void account() {
        users.save(new WorkspaceUser("auth-fixture", encoder.encode("fixture-password"), "검증 사용자",
                "inventory:read,inventory:write"));
    }

    private MvcResult session(MockHttpSession session) throws Exception {
        var request = get("/api/auth/session");
        if (session != null) request.session(session);
        return mvc.perform(request).andExpect(status().isOk()).andReturn();
    }

    private CsrfToken token(MvcResult result) {
        return (CsrfToken) result.getRequest().getAttribute(CsrfToken.class.getName());
    }

    private MockHttpSession login() throws Exception {
        MvcResult anonymous = session(null);
        MockHttpSession before = (MockHttpSession) anonymous.getRequest().getSession(false);
        String beforeId = before.getId();
        CsrfToken csrf = token(anonymous);
        MvcResult authenticated = mvc.perform(post("/api/auth/login").session(before)
                .with(request -> { request.setRequestedSessionId(beforeId); request.setRequestedSessionIdValid(true); return request; })
                .param("username", "auth-fixture").param("password", "fixture-password")
                .header(csrf.getHeaderName(), csrf.getToken()))
                .andExpect(status().isOk()).andExpect(jsonPath("$.authenticated").value(true)).andReturn();
        MockHttpSession after = (MockHttpSession) authenticated.getRequest().getSession(false);
        assertNotEquals(beforeId, after.getId(), "Login must rotate the session identifier");
        return after;
    }

    @Test
    void anonymousCanReadSessionButCannotAccessBusinessApi() throws Exception {
        mvc.perform(get("/api/auth/session")).andExpect(status().isOk())
                .andExpect(jsonPath("$.authenticated").value(false)).andExpect(jsonPath("$.csrf.token").isString());
        mvc.perform(get("/api/inventory")).andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.error").value("AUTH_REQUIRED"));
    }

    @Test
    void specificationAndGeneratedRoutesRequireWorkspaceAuthority() throws Exception {
        mvc.perform(get("/api/specs/screens/ZDE0001/releases/1").with(user("reader").authorities(() -> "inventory:read")))
                .andExpect(status().isForbidden());
        mvc.perform(get("/api/specs/screens/INVALID/releases/1").with(user("admin").authorities(() -> "workspace:admin")))
                .andExpect(status().isBadRequest());
    }

    @Test
    void realPasswordLoginPersistsIdentityAndAllowsAuthorizedRead() throws Exception {
        MockHttpSession authenticated = login();
        mvc.perform(get("/api/auth/session").session(authenticated)).andExpect(status().isOk())
                .andExpect(jsonPath("$.user.username").value("auth-fixture"))
                .andExpect(jsonPath("$.user.displayName").value("검증 사용자"));
        mvc.perform(get("/api/inventory").session(authenticated)).andExpect(status().isOk());
    }

    @Test
    void loginAndMutationsRejectMissingCsrf() throws Exception {
        mvc.perform(post("/api/auth/login").param("username", "auth-fixture").param("password", "fixture-password"))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.error").value("CSRF_REQUIRED"));
        mvc.perform(post("/api/inventory").session(login()).contentType("application/json").content("{}"))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.error").value("CSRF_REQUIRED"));
    }

    @Test
    void incorrectPasswordDoesNotAuthenticate() throws Exception {
        mvc.perform(post("/api/auth/login").with(csrf()).param("username", "auth-fixture").param("password", "incorrect"))
                .andExpect(status().isUnauthorized()).andExpect(jsonPath("$.error").value("INVALID_CREDENTIALS"));
    }

    @Test
    void readPermissionDoesNotPermitWrites() throws Exception {
        var reader = user("reader").authorities(() -> "inventory:read");
        mvc.perform(get("/api/inventory").with(reader)).andExpect(status().isOk());
        mvc.perform(post("/api/inventory").with(reader).with(csrf()).contentType("application/json").content("{}"))
                .andExpect(status().isForbidden()).andExpect(jsonPath("$.error").value("FORBIDDEN"));
    }

    @Test
    void logoutInvalidatesSessionAndRequiresFreshAuthentication() throws Exception {
        MockHttpSession authenticated = login();
        CsrfToken fresh = token(session(authenticated));
        mvc.perform(post("/api/auth/logout").session(authenticated).header(fresh.getHeaderName(), fresh.getToken()))
                .andExpect(status().isNoContent());
        assertTrue(authenticated.isInvalid());
        mvc.perform(get("/api/inventory")).andExpect(status().isUnauthorized());
    }
}
