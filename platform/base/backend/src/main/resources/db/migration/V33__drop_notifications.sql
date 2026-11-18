-- Notifications were taken out again (the app does not notify); V32 stays so that databases it already ran on still validate.
DROP TABLE IF EXISTS sys_notifications;
