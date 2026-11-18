-- Each screen keeps its own history (h_<key>, made beside r_<key> by the application, which also carries the rows of the old shared
-- table app_record_history over and then drops it). The screen that read every screen's history in one place goes.
DELETE FROM sys_programs WHERE program_code = 'SYS0013';
