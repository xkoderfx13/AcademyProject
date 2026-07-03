-- ============================================================
-- IAProject - Database Setup (MySQL Workbench - Schema: ia)
-- الخطوات:
--   1. افتح MySQL Workbench وتأكد إن السكيما ia موجودة
--   2. شغّل: python manage.py migrate
--   3. شغّل هذا الملف على السكيما ia
--   4. شغّل: python manage.py createsuperuser
-- ============================================================

USE ia;

-- ============================================================
-- Extra columns on auth_user
-- ============================================================
ALTER TABLE auth_user
    ADD COLUMN IF NOT EXISTS discord_id VARCHAR(50) DEFAULT NULL,
    ADD COLUMN IF NOT EXISTS is_owner   TINYINT(1)  DEFAULT 0,
    ADD COLUMN IF NOT EXISTS points     INT         DEFAULT 0;

-- ============================================================
-- Reports table
-- ============================================================
CREATE TABLE IF NOT EXISTS reports (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    name         VARCHAR(255) NOT NULL,
    content      TEXT NOT NULL,
    evidence_url VARCHAR(500) NOT NULL,
    status       TINYINT(1) DEFAULT 0,
    is_deleted   TINYINT(1) DEFAULT 0,
    perm         TINYINT(1) DEFAULT 0,
    closed_by_id INT DEFAULT NULL,
    FOREIGN KEY (closed_by_id) REFERENCES auth_user(id) ON DELETE SET NULL
);

-- ============================================================
-- Forms table
-- ============================================================
CREATE TABLE IF NOT EXISTS forms (
    form_id   INT AUTO_INCREMENT PRIMARY KEY,
    form_name VARCHAR(100) NOT NULL,
    form_url  VARCHAR(200),
    title     VARCHAR(100)
);

-- ============================================================
-- Privileges table
-- ============================================================
CREATE TABLE IF NOT EXISTS privilage (
    priv_id   INT AUTO_INCREMENT PRIMARY KEY,
    priv_name VARCHAR(100) NOT NULL,
    form_id   INT NOT NULL,
    FOREIGN KEY (form_id) REFERENCES forms(form_id) ON DELETE CASCADE
);

-- ============================================================
-- User privileges table
-- ============================================================
CREATE TABLE IF NOT EXISTS user_priv (
    id      INT AUTO_INCREMENT PRIMARY KEY,
    user    INT NOT NULL,
    priv_id INT NOT NULL,
    status  TINYINT(1) DEFAULT 0,
    UNIQUE KEY uniq_user_priv (user, priv_id),
    FOREIGN KEY (user)    REFERENCES auth_user(id) ON DELETE CASCADE,
    FOREIGN KEY (priv_id) REFERENCES privilage(priv_id) ON DELETE CASCADE
);

-- ============================================================
-- Forms Data
-- ============================================================
INSERT IGNORE INTO forms (form_id, form_name, form_url, title) VALUES
(1, 'البلاغات',    '/home/reports/', 'البلاغات'),
(2, 'لوحة التحكم', '/home/console/', 'لوحة التحكم'),
(3, 'النقاط',      '/home/points/',  'النقاط'),
(4, 'الإدارة',     '/home/users/',   'الإدارة');

-- ============================================================
-- Privileges Data
-- IDs 1,4,9,13 = default ON  |  New user gets: 1,3,4,21
-- ============================================================

-- Form 1: البلاغات
INSERT IGNORE INTO privilage (priv_id, priv_name, form_id) VALUES
(1, 'الوصول',          1),
(2, 'التعامل',         1),
(3, 'الحذف',           1),
(4, 'عرض المحذوفه',    1),
(5, 'إستعادة بلاغ',   1),
(6, 'مشاهدة الدلائل', 1),
(7, 'حذف نهائي',       1),
(8, 'الإغلاق',         1);

-- Form 2: لوحة التحكم
INSERT IGNORE INTO privilage (priv_id, priv_name, form_id) VALUES
(9,  'الوصول',       2),
(10, 'إضافة  شؤون', 2),
(11, 'حذف شؤون',     2),
(12, 'تعديل شؤون',   2);

-- Form 3: النقاط
INSERT IGNORE INTO privilage (priv_id, priv_name, form_id) VALUES
(13, 'الوصول',               3),
(14, 'منح نقاط',             3),
(15, 'خصم نقاط',             3),
(16, 'تصغير نقاط',           3),
(17, 'تصفير نقاط',           3),
(18, 'زر إجراءات جماعية',    3),
(19, 'تصفير الجميع',         3),
(20, 'إضافة للجميع',         3);

-- Form 4: الإدارة
INSERT IGNORE INTO privilage (priv_id, priv_name, form_id) VALUES
(21, 'الوصول', 4),
(22, 'إدارة',  4);
