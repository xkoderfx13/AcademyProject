"""
سكريبت لإنشاء تقديم تجريبي كامل مع نتيجة اختبار.
شغّله بـ: python seed_application.py
"""
import os
import django
import random

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
django.setup()

from django.utils import timezone
from main.models import Application, Question, TestSession, ApplicantAnswer

DISCORD_ID = '111222333444555666'
CHARACTER  = 'خالد الحربي'

# تجنب التكرار
if Application.objects.filter(discord_id=DISCORD_ID).exists():
    print(f'التقديم موجود مسبقاً (discord_id={DISCORD_ID})')
    app = Application.objects.get(discord_id=DISCORD_ID)
else:
    app = Application.objects.create(
        discord_id=DISCORD_ID,
        character_name=CHARACTER,
        status='testing',
        test_started_at=timezone.now(),
    )
    print(f'تم إنشاء التقديم: id={app.id}')

# تحقق من وجود أسئلة
q_ids = list(Question.objects.values_list('id', flat=True))
if len(q_ids) < 10:
    print('خطأ: عدد الأسئلة أقل من 10. شغّل أولاً: python manage.py load_sample_questions')
    exit(1)

# إنشاء جلسة الاختبار إذا لم تكن موجودة
if app.sessions.exists():
    sess = app.sessions.order_by('-started_at').first()
    print(f'الجلسة موجودة مسبقاً: id={sess.id}')
else:
    chosen = random.sample(q_ids, 10)
    sess = TestSession.objects.create(
        application=app,
        is_active=True,
        started_at=timezone.now(),
        questions_order=','.join(str(x) for x in chosen),
        discord_id=DISCORD_ID,
    )
    print(f'تم إنشاء جلسة الاختبار: id={sess.id}')

# إنشاء الإجابات إذا لم تكن موجودة
if not sess.answers.exists():
    questions = list(Question.objects.filter(id__in=sess.question_ids()))
    correct_count = 0
    for q in questions:
        # 70% احتمال الإجابة الصحيحة
        if random.random() < 0.7:
            chosen_index = q.correct_index
            is_correct = True
            correct_count += 1
        else:
            wrong = [i for i in range(4) if i != q.correct_index]
            chosen_index = random.choice(wrong)
            is_correct = False

        ApplicantAnswer.objects.create(
            session=sess,
            question=q,
            selected_index=chosen_index,
            is_correct=is_correct,
        )

    sess.score = (correct_count / 10.0) * 10.0
    sess.is_active = False
    sess.finished_at = timezone.now()
    sess.save()

    app.status = 'completed'
    app.save()

    print(f'الإجابات: {correct_count}/10 صحيحة — النتيجة: {sess.score}/10')
else:
    print(f'الإجابات موجودة مسبقاً — النتيجة: {sess.score}/10')

print(f'\nرابط التفاصيل في لوحة التحكم: /admin/applications/{app.id}/')
print(f'Discord ID: {DISCORD_ID}  |  الاسم: {CHARACTER}  |  الحالة: {app.status}')
