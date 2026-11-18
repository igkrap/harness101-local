-- Board in the usual community style: view counts and comments.
ALTER TABLE sys_posts ADD COLUMN views INT NOT NULL DEFAULT 0;
CREATE TABLE sys_post_comments (
    comment_id BIGSERIAL PRIMARY KEY,
    post_id BIGINT NOT NULL REFERENCES sys_posts(post_id) ON DELETE CASCADE,
    body VARCHAR(2000) NOT NULL,
    created_by VARCHAR(100) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX sys_post_comments_post ON sys_post_comments (post_id, comment_id);
