import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'myproject.settings')
django.setup()

from main.models import User

username = 'admin'
password = 'admin123'
full_name = 'System Administrator'
rank = 'dev'

if User.objects.filter(username=username).exists():
    print(f"المستخدم '{username}' موجود مسبقاً.")
else:
    u = User(username=username, full_name=full_name, rank=rank)
    u.set_password(password)
    u.save()
    print(f"تم إنشاء المستخدم '{username}' بنجاح!")
    print(f"  الرتبة : {rank}")
    print(f"  كلمة المرور : {password}")
