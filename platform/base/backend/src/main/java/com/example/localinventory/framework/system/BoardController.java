package com.example.localinventory.framework.system;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * The board. A post is a notice (NOTICE) or a general post (GENERAL). Every signed-in user reads published posts and
 * writes general ones, changing or deleting only their own. Administrators also write notices, pin and hide posts,
 * and may change or delete any post.
 */
@RestController
public class BoardController {
    private static final String COLUMNS = "p.post_id AS id, p.post_type AS type, p.title, p.pinned, p.published, p.created_by AS \"createdBy\", "
            + "COALESCE(u.display_name, p.created_by) AS writer, p.created_at AS \"createdAt\", p.updated_at AS \"updatedAt\", p.views, "
            + "(SELECT COUNT(*) FROM sys_post_comments c WHERE c.post_id = p.post_id) AS comments";
    private static final String FROM = " FROM sys_posts p LEFT JOIN workspace_users u ON u.username = p.created_by ";
    private final JdbcTemplate jdbc;
    private final SystemAccessService access;
    private final LiveEvents live;
    public BoardController(JdbcTemplate jdbc, SystemAccessService access, LiveEvents live) { this.jdbc = jdbc; this.access = access; this.live = live; }

    public record PostInput(String type, String title, String body, Boolean pinned, Boolean published) {}

    /**
     * One page of the list: notices first (pinned ones on top), then newest. type = NOTICE | GENERAL | empty for both.
     * field = title | writer | body chooses what keyword looks in. Hidden posts show only to administrators and their writer.
     */
    @GetMapping("/api/auth/posts")
    public Map<String, Object> list(@RequestParam(defaultValue = "") String type, @RequestParam(defaultValue = "") String keyword,
            @RequestParam(defaultValue = "title") String field, @RequestParam(defaultValue = "1") int page, @RequestParam(defaultValue = "20") int size,
            Authentication authentication) {
        String column = switch (field) { case "writer" -> "COALESCE(u.display_name, p.created_by)"; case "body" -> "p.body"; default -> "p.title"; };
        StringBuilder where = new StringBuilder("WHERE LOWER(" + column + ") LIKE ?");
        List<Object> args = new ArrayList<>(List.of("%" + keyword.trim().toLowerCase() + "%"));
        if (type.equals("NOTICE") || type.equals("GENERAL")) { where.append(" AND p.post_type = ?"); args.add(type); }
        if (!admin(authentication)) { where.append(" AND (p.published OR p.created_by = ?)"); args.add(authentication.getName()); }
        Long total = jdbc.queryForObject("SELECT COUNT(*)" + FROM + where, Long.class, args.toArray());
        int limit = Math.max(1, Math.min(100, size)), offset = Math.max(0, page - 1) * limit;
        args.add(limit); args.add(offset);
        List<Map<String, Object>> items = jdbc.queryForList("SELECT " + COLUMNS + FROM + where
                + " ORDER BY p.pinned DESC, (p.post_type = 'NOTICE') DESC, p.created_at DESC, p.post_id DESC LIMIT ? OFFSET ?", args.toArray());
        return Map.of("total", total == null ? 0 : total, "page", Math.max(1, page), "size", limit, "items", items);
    }

    /** The post with its comments and the neighbouring posts; reading counts as a view (count=false to skip). */
    @GetMapping("/api/auth/posts/{id}")
    public Map<String, Object> one(@PathVariable long id, @RequestParam(defaultValue = "true") boolean count, Authentication authentication) {
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT " + COLUMNS + ", p.body" + FROM + "WHERE p.post_id = ?", id);
        if (rows.isEmpty()) throw missing();
        Map<String, Object> post = new java.util.LinkedHashMap<>(rows.get(0));
        boolean admin = admin(authentication);
        if (!Boolean.TRUE.equals(post.get("published")) && !admin && !authentication.getName().equals(post.get("createdBy"))) throw missing();
        if (count) { jdbc.update("UPDATE sys_posts SET views = views + 1 WHERE post_id = ?", id); post.put("views", ((Number) post.get("views")).intValue() + 1); }
        post.put("commentList", comments(id));
        String visible = admin ? "" : " AND published";
        post.put("previous", neighbour("SELECT post_id AS id, title FROM sys_posts WHERE post_id < ?" + visible + " ORDER BY post_id DESC LIMIT 1", id));
        post.put("next", neighbour("SELECT post_id AS id, title FROM sys_posts WHERE post_id > ?" + visible + " ORDER BY post_id ASC LIMIT 1", id));
        return post;
    }

    public record CommentInput(String body) {}

    @PostMapping("/api/auth/posts/{id}/comments")
    public List<Map<String, Object>> comment(@PathVariable long id, @RequestBody CommentInput input, Authentication authentication) {
        String body = input.body() == null ? "" : input.body().trim();
        if (body.isEmpty() || body.length() > 2000) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "댓글을 입력하세요. (2,000자 이하)");
        if (jdbc.queryForObject("SELECT COUNT(*) FROM sys_posts WHERE post_id = ?", Integer.class, id) == 0) throw missing();
        jdbc.update("INSERT INTO sys_post_comments (post_id, body, created_by) VALUES (?, ?, ?)", id, body, authentication.getName());
        return comments(id);
    }

    @DeleteMapping("/api/auth/posts/{id}/comments/{commentId}")
    public List<Map<String, Object>> deleteComment(@PathVariable long id, @PathVariable long commentId, Authentication authentication) {
        List<String> writer = jdbc.queryForList("SELECT created_by FROM sys_post_comments WHERE comment_id = ? AND post_id = ?", String.class, commentId, id);
        if (writer.isEmpty()) throw missing();
        if (!admin(authentication) && !authentication.getName().equals(writer.get(0))) throw new ResponseStatusException(HttpStatus.FORBIDDEN, "내가 쓴 댓글만 지울 수 있습니다.");
        jdbc.update("DELETE FROM sys_post_comments WHERE comment_id = ?", commentId);
        return comments(id);
    }

    private List<Map<String, Object>> comments(long id) {
        return jdbc.queryForList("SELECT c.comment_id AS id, c.body, c.created_by AS \"createdBy\", COALESCE(u.display_name, c.created_by) AS writer, c.created_at AS \"createdAt\" "
                + "FROM sys_post_comments c LEFT JOIN workspace_users u ON u.username = c.created_by WHERE c.post_id = ? ORDER BY c.comment_id", id);
    }
    private Map<String, Object> neighbour(String sql, long id) {
        List<Map<String, Object>> rows = jdbc.queryForList(sql, id);
        return rows.isEmpty() ? null : rows.get(0);
    }

    @PostMapping("/api/auth/posts")
    public Map<String, Object> create(@RequestBody PostInput input, Authentication authentication) {
        boolean admin = admin(authentication);
        Long id = jdbc.queryForObject("INSERT INTO sys_posts (post_type, title, body, pinned, published, created_by) VALUES (?, ?, ?, ?, ?, ?) RETURNING post_id", Long.class,
                type(input, admin), title(input), body(input), admin && Boolean.TRUE.equals(input.pinned()), !admin || input.published() == null || input.published(), authentication.getName());
        live.publish("posts");
        return Map.of("id", id);
    }

    @PutMapping("/api/auth/posts/{id}")
    public Map<String, Object> update(@PathVariable long id, @RequestBody PostInput input, Authentication authentication) {
        boolean admin = admin(authentication);
        Map<String, Object> current = owned(id, authentication, admin);
        // Only administrators change the kind, the pin and whether a post is shown.
        String type = admin ? type(input, true) : String.valueOf(current.get("post_type"));
        boolean pinned = admin ? Boolean.TRUE.equals(input.pinned()) : Boolean.TRUE.equals(current.get("pinned"));
        boolean published = admin ? input.published() == null || input.published() : Boolean.TRUE.equals(current.get("published"));
        jdbc.update("UPDATE sys_posts SET post_type = ?, title = ?, body = ?, pinned = ?, published = ?, updated_by = ?, updated_at = CURRENT_TIMESTAMP WHERE post_id = ?",
                type, title(input), body(input), pinned, published, authentication.getName(), id);
        live.publish("posts");
        return Map.of("id", id);
    }

    @DeleteMapping("/api/auth/posts/{id}")
    public Map<String, Object> delete(@PathVariable long id, Authentication authentication) {
        owned(id, authentication, admin(authentication));
        jdbc.update("DELETE FROM sys_posts WHERE post_id = ?", id);
        live.publish("posts");
        return Map.of("deleted", true);
    }

    private Map<String, Object> owned(long id, Authentication authentication, boolean admin) {
        List<Map<String, Object>> rows = jdbc.queryForList("SELECT post_type, pinned, published, created_by FROM sys_posts WHERE post_id = ?", id);
        if (rows.isEmpty()) throw missing();
        if (!admin && !authentication.getName().equals(rows.get(0).get("created_by"))) throw new ResponseStatusException(HttpStatus.FORBIDDEN, "내가 쓴 글만 고치거나 지울 수 있습니다.");
        return rows.get(0);
    }
    private boolean admin(Authentication authentication) {
        return access.isAdmin(authentication.getName(), authentication.getAuthorities().stream().map(authority -> authority.getAuthority()).toList());
    }
    private static String type(PostInput input, boolean admin) {
        boolean notice = "NOTICE".equals(input.type());
        if (notice && !admin) throw new ResponseStatusException(HttpStatus.FORBIDDEN, "공지는 관리자만 쓸 수 있습니다.");
        return notice ? "NOTICE" : "GENERAL";
    }
    private static String title(PostInput input) {
        String title = input.title() == null ? "" : input.title().trim();
        if (title.isEmpty() || title.length() > 200) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "제목을 입력하세요. (200자 이하)");
        return title;
    }
    private static String body(PostInput input) {
        String body = input.body() == null ? "" : input.body();
        if (body.length() > 20000) throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "내용은 20,000자 이하여야 합니다.");
        return body;
    }
    private static ResponseStatusException missing() { return new ResponseStatusException(HttpStatus.NOT_FOUND, "게시글을 찾지 못했습니다."); }
}
