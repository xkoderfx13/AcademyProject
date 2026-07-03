-- ============================================================
--  Academy Project - MySQL Database
--  الخطوة 1: شغّل هذا الكويري في MySQL Workbench
--  الخطوة 2: اتبع التعليمات في الأسفل لتشغيل Django
-- ============================================================

CREATE DATABASE IF NOT EXISTS academy_db
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE academy_db;

-- ============================================================
-- بعد تشغيل الكويري أعلاه، افتح CMD في مجلد المشروع وشغّل:
--
--   pip install -r requirements.txt
--   python manage.py migrate
--   python manage.py load_sample_questions
--   python create_admin.py
--
-- ثم شغّل السيرفر:
--   python manage.py runserver
-- ============================================================
