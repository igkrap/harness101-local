-- Notices become a board: every post is a notice (공지, administrators) or a general post (일반, any user).
ALTER TABLE sys_notices RENAME TO sys_posts;
ALTER TABLE sys_posts RENAME COLUMN notice_id TO post_id;
ALTER TABLE sys_posts ADD COLUMN post_type VARCHAR(20) NOT NULL DEFAULT 'GENERAL';   -- NOTICE | GENERAL
UPDATE sys_posts SET post_type = 'NOTICE';
CREATE INDEX sys_posts_recent ON sys_posts (post_type, created_at DESC);
UPDATE sys_programs SET program_name = '게시판', keywords = '게시판,공지,공지사항,게시글,알림,안내,자유' WHERE program_code = 'SYS0009';
UPDATE sys_menus SET menu_name = '게시판' WHERE program_code = 'SYS0009' AND menu_name = '공지사항';
