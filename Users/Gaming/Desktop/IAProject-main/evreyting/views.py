from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages 
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import connection
from django.views.decorators.csrf import csrf_exempt
from datetime import datetime
import requests
import json
from django.contrib.auth.hashers import make_password
import os
import dotenv

dotenv.load_dotenv()

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SERVER_ID = os.getenv("DISCORD_SERVER_ID")
WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")



import os, requests, dotenv

dotenv.load_dotenv()

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
SERVER_ID = os.getenv("DISCORD_SERVER_ID")

headers = {"Authorization": f"Bot {BOT_TOKEN}"}

r = requests.get(f"https://discord.com/api/v10/guilds/{SERVER_ID}", headers=headers)
print("Status:", r.status_code)
print(r.text)



@login_required(login_url='ialogin')
@require_http_methods(["POST"])
@csrf_exempt
def permanent_delete_report(request, report_id):
    user_privs = get_detailed_privileges(request.user.id, 'البلاغات')
    
    if user_privs.get('حذف نهائي', 0) != 1:
        return JsonResponse({'success': False, 'message': 'لا تملك صلاحية الحذف النهائي للبلاغات.'})
    
    try:
        if not report_id:
            return JsonResponse({'success': False, 'message': 'معرف البلاغ غير صحيح.'})
        
        report_id = int(report_id)
        
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM reports WHERE id = %s", [report_id])
            report_exists = cursor.fetchone()
            
            if not report_exists:
                return JsonResponse({'success': False, 'message': 'البلاغ غير موجود.'})
            
            cursor.execute("UPDATE reports SET perm = 1 WHERE id = %s", [report_id])
            
        return JsonResponse({'success': True, 'message': 'تم الحذف النهائي للبلاغ بنجاح.'})
        
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'حدث خطأ أثناء الحذف النهائي: {str(e)}'})

def initialize_privileges_system():
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM user_priv")
        
        cursor.execute("SELECT id FROM auth_user")
        users = [row[0] for row in cursor.fetchall()]
        
        cursor.execute("SELECT priv_id, form_id FROM privilage")
        privileges = cursor.fetchall()
        
        for user_id in users:
            for priv_id, form_id in privileges:
                status = 1 if priv_id in [1, 4, 9, 13] else 0
                cursor.execute(
                    "INSERT INTO user_priv (user, priv_id, status) VALUES (%s, %s, %s)",
                    [user_id, priv_id, status]
                )
        
        print(f"تم تهيئة {len(users)} مستخدم × {len(privileges)} صلاحية = {len(users)*len(privileges)} سجل")

def get_detailed_privileges(user_id, form_name):
    if not user_id:
        return {}
        
    query = """
        SELECT
            p.priv_name,
            COALESCE(up.status, 0) AS status
        FROM
            privilage p
        JOIN
            forms f ON p.form_id = f.form_id
        LEFT JOIN
            user_priv up ON p.priv_id = up.priv_id AND up.user = %s
        WHERE
            f.form_name = %s
    """
    
    with connection.cursor() as cursor:
        cursor.execute(query, [user_id, form_name])
        results = cursor.fetchall()
        privileges = {row[0]: row[1] for row in results}
        
    return privileges

def get_user_forms(user_id):
    if not user_id:
        return []
        
    query = """
        SELECT DISTINCT
            f.form_id,
            f.form_name,
            f.form_url,
            f.title
        FROM
            forms f
        JOIN
            privilage p ON f.form_id = p.form_id
        JOIN
            user_priv up ON p.priv_id = up.priv_id
        WHERE
            up.user = %s 
            AND up.status = 1 
            AND p.priv_name = 'الوصول'
        ORDER BY f.form_id
    """
    
    with connection.cursor() as cursor:
        cursor.execute(query, [user_id])
        columns = [col[0] for col in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

def index(request):
    if request.method == "POST":
        name = request.POST.get("name")
        content = request.POST.get("content")
        evidence_url = request.POST.get("evidence_url")

        if name and content and evidence_url:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO reports (name, content, evidence_url) VALUES (%s, %s, %s)",
                        [name, content, evidence_url]
                    )
                messages.success(request, 'تم تسجيل الشكوى بنجاح!')
            except Exception as e:
                messages.error(request, f'حدث خطأ أثناء الحفظ: {e}')
        else:
            messages.warning(request, 'بيانات ناقصة، لم يتم تسجيل الشكوى.')
        return redirect('index')
    
    return render(request, "pages/index.html")

def ialoing(request):
    if request.method == "POST":
        username = request.POST["username"]
        password = request.POST["password"]
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect("home")
        return render(request, "pages/ialogin.html", {"error": "اسم المستخدم أو كلمة المرور غير صحيحة"})
    return render(request, "pages/ialogin.html")

@login_required(login_url='ialogin')
@require_http_methods(["POST"])
@csrf_exempt
def delete_report(request, report_id):
    user_privs = get_detailed_privileges(request.user.id, 'البلاغات')
    
    if user_privs.get('الحذف', 0) != 1:
        return JsonResponse({'success': False, 'message': 'لا تملك صلاحية حذف البلاغات.'})
    
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE reports SET is_deleted = 1 WHERE id = %s", 
                [report_id]
            )
        return JsonResponse({'success': True, 'message': 'تم حذف البلاغ بنجاح.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'حدث خطأ أثناء حذف البلاغ: {str(e)}'})

@login_required(login_url='ialogin')
@require_http_methods(["POST"])
@csrf_exempt
def update_user(request, user_id):
    user_privs = get_detailed_privileges(request.user.id, 'لوحة التحكم')
    
    if user_privs.get('تعديل شؤون', 0) != 1:
        return JsonResponse({'success': False, 'message': 'لا تملك صلاحية تعديل الشؤون.'})
    
    try:
        username = request.POST.get('username')
        email = request.POST.get('email')
        first_name = request.POST.get('first_name')
        discord_id = request.POST.get('discord_id', '')
        user_type = request.POST.get('user_type')
        
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM auth_user WHERE username = %s AND id != %s", [username, user_id])
            if cursor.fetchone()[0] > 0:
                return JsonResponse({'success': False, 'message': 'اسم المستخدم موجود مسبقاً'})
            
            cursor.execute(
                "UPDATE auth_user SET username = %s, email = %s, first_name = %s, discord_id = %s, is_staff = %s, is_superuser = %s WHERE id = %s",
                [username, email, first_name, discord_id,
                 1 if user_type in ['management', 'deputy'] else 0,
                 1 if user_type == 'deputy' else 0,
                 user_id]
            )
            
            if discord_id:
                current_role = 'deputy' if user_type == 'deputy' else 'management' if user_type == 'management' else 'member'
                discord_result = assign_discord_role(discord_id, current_role, request.user.username)
                if not discord_result['success']:
                    return JsonResponse({'success': False, 'message': f'تم تحديث المستخدم ولكن فشل تحديث رتبة الديسكورد: {discord_result["message"]}'})
        
        return JsonResponse({'success': True, 'message': 'تم تحديث المستخدم بنجاح.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'حدث خطأ أثناء تحديث المستخدم: {str(e)}'})

@login_required(login_url='ialogin')
def console(request):
    user_privs = get_detailed_privileges(request.user.id, 'لوحة التحكم')
    
    if user_privs.get('الوصول', 0) != 1:
        return render(request, "pages/access_denied.html")

    user_forms = get_user_forms(request.user.id)
    
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, username, email, is_staff, is_superuser, 
                   COALESCE(is_owner, 0) as is_owner, 
                   COALESCE(discord_id, '') as discord_id,
                   first_name
            FROM auth_user 
            ORDER BY is_owner DESC, is_superuser DESC, is_staff DESC, username
        """)
        columns = [col[0] for col in cursor.description]
        users = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        cursor.execute("SELECT COUNT(*) FROM auth_user")
        users_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM auth_user WHERE is_staff = 1 OR is_superuser = 1")
        staff_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM auth_user WHERE is_staff = 0 AND is_superuser = 0")
        regular_count = cursor.fetchone()[0]
    
    can_add = user_privs.get('إضافة  شؤون', 0) == 1
    can_delete = user_privs.get('حذف شؤون', 0) == 1
    can_edit = user_privs.get('تعديل شؤون', 0) == 1

    context = {
        'forms': user_forms,
        'users': users,
        'users_count': users_count,
        'staff_count': staff_count,
        'regular_count': regular_count,
        'user_privs': user_privs,
        'can_add': can_add,
        'can_delete': can_delete,
        'can_edit': can_edit,
    }
    
    if request.method == "POST":
        action = request.POST.get('action')
        
        if action == 'add':
            if not can_add:
                return JsonResponse({'success': False, 'message': 'لا تملك صلاحية إضافة شؤون'})
                
            username = request.POST.get('username')
            email = request.POST.get('email')
            first_name = request.POST.get('first_name')
            password = request.POST.get('password')
            user_type = request.POST.get('user_type')
            checkpoint_toggle = request.POST.get('checkpoint_toggle')
            discord_id = request.POST.get('discord_id', '')
            discord_role = request.POST.get('discord_role', 'member')
            
            if not username or not email or not first_name or not password:
                return JsonResponse({'success': False, 'message': 'جميع الحقول مطلوبة'})
            
            try:
                hashed_password = make_password(password)
                
                with connection.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM auth_user WHERE username = %s", [username])
                    if cursor.fetchone()[0] > 0:
                        return JsonResponse({'success': False, 'message': 'اسم المستخدم موجود مسبقاً'})
                    
                    cursor.execute(
                        """
                        INSERT INTO auth_user 
                        (username, email, first_name, password, date_joined, is_staff, is_superuser, is_active)
                        VALUES (%s, %s, %s, %s, NOW(), %s, %s, 1)
                        """,
                        [username, email, first_name, hashed_password, 
                         1 if user_type in ['management', 'deputy'] else 0,
                         1 if user_type == 'deputy' else 0]
                    )

                    priv_ids = [1, 3, 4, 21]
                    for priv_id in priv_ids:
                        cursor.execute(
                            """
                            INSERT INTO user_priv (user, priv_id, status)
                            SELECT id, %s, %s
                            FROM auth_user
                            WHERE username = %s
                            """,
                            [priv_id, 1, username]
                        )

                    # تحديث discord_id لو مطلوب
                    if checkpoint_toggle and discord_id:
                        cursor.execute(
                            "UPDATE auth_user SET discord_id = %s WHERE username = %s",
                            [discord_id, username]
                        )
                        
                        if assign_discord_role:
                            discord_result = assign_discord_role(discord_id, discord_role, request.user.username)
                            if not discord_result['success']:
                                return JsonResponse({'success': False, 'message': f'تم إنشاء المستخدم ولكن فشل إعطاء رتبة الديسكورد: {discord_result["message"]}'})
                
                return JsonResponse({'success': True, 'message': 'تم إضافة المستخدم بنجاح!'})
                
            except Exception as e:
                return JsonResponse({'success': False, 'message': f'حدث خطأ: {str(e)}'})
        
        elif action == 'delete':
            if not can_delete:
                return JsonResponse({'success': False, 'message': 'لا تملك صلاحية حذف شؤون'})
                
            user_id = request.POST.get('user_id')
            
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT discord_id, is_staff, is_superuser, username FROM auth_user WHERE id = %s", [user_id])
                    result = cursor.fetchone()
                    
                    if not result:
                        return JsonResponse({'success': False, 'message': 'المستخدم غير موجود'})
                    
                    discord_id = result[0] if result and result[0] else None
                    is_staff = result[1] if result else 0
                    is_superuser = result[2] if result else 0
                    username = result[3] if result else ''
                    
                    if request.user.username == username:
                        return JsonResponse({'success': False, 'message': 'لا يمكنك حذف حسابك الخاص'})
                    
                    cursor.execute("DELETE FROM auth_user WHERE id = %s", [user_id])
                    
                    if discord_id and remove_discord_role:
                        role_type = 'deputy' if is_superuser else 'management' if is_staff else 'member'
                        remove_discord_role(discord_id, role_type, request.user.username)
                
                return JsonResponse({'success': True, 'message': 'تم حذف المستخدم بنجاح!'})
            except Exception as e:
                return JsonResponse({'success': False, 'message': f'حدث خطأ: {str(e)}'})
        
        elif action == 'update':
            if not can_edit:
                return JsonResponse({'success': False, 'message': 'لا تملك صلاحية تعديل شؤون'})
                
            user_id = request.POST.get('user_id')
            username = request.POST.get('username')
            email = request.POST.get('email')
            first_name = request.POST.get('first_name')
            discord_id = request.POST.get('discord_id', '')
            user_type = request.POST.get('user_type')
            
            if not username or not email or not first_name:
                return JsonResponse({'success': False, 'message': 'جميع الحقول مطلوبة'})
            
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM auth_user WHERE username = %s AND id != %s", [username, user_id])
                    if cursor.fetchone()[0] > 0:
                        return JsonResponse({'success': False, 'message': 'اسم المستخدم موجود مسبقاً'})
                    
                    cursor.execute(
                        """
                        UPDATE auth_user 
                        SET username = %s, email = %s, first_name = %s, discord_id = %s, 
                            is_staff = %s, is_superuser = %s 
                        WHERE id = %s
                        """,
                        [username, email, first_name, discord_id,
                         1 if user_type in ['management', 'deputy'] else 0,
                         1 if user_type == 'deputy' else 0,
                         user_id]
                    )
                    
                    if discord_id and assign_discord_role:
                        current_role = 'deputy' if user_type == 'deputy' else 'management' if user_type == 'management' else 'member'
                        discord_result = assign_discord_role(discord_id, current_role, request.user.username)
                        if not discord_result['success']:
                            return JsonResponse({'success': False, 'message': f'تم تحديث المستخدم ولكن فشل تحديث رتبة الديسكورد: {discord_result["message"]}'})
                
                return JsonResponse({'success': True, 'message': 'تم تحديث المستخدم بنجاح.'})
            except Exception as e:
                return JsonResponse({'success': False, 'message': f'حدث خطأ أثناء تحديث المستخدم: {str(e)}'})
    
    return render(request, "pages/console.html", context)


def assign_discord_role(discord_id, role_type, admin_name):
    BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    SERVER_ID = os.getenv("DISCORD_SERVER_ID")
    WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    
    role_ids = {
        'deputy': '1430189316411228182',
        'management': '1430198706740793416',
        'member': '1430189364121702541'
    }
    
    role_names = {
        'deputy': 'Deputy Of Internal Affairs',
        'management': 'Internal Affairs Management', 
        'member': 'Internal Affairs Member'
    }
    
    role_id = role_ids.get(role_type)
    role_name = role_names.get(role_type)
    
    if not role_id:
        return {'success': False, 'message': 'نوع الرتبة غير صحيح'}
    
    headers = {
        "Authorization": f"Bot {BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        guild_url = f"https://discord.com/api/v10/guilds/{SERVER_ID}"
        guild_response = requests.get(guild_url, headers=headers)
        if guild_response.status_code != 200:
            return {'success': False, 'message': 'البوت لا يستطيع الوصول للسيرفر'}
        
        role_url = f"https://discord.com/api/v10/guilds/{SERVER_ID}/members/{discord_id}/roles/{role_id}"
        role_response = requests.put(role_url, headers=headers)
        
        print(f"Discord API Response: {role_response.status_code}")
        
        if role_response.status_code == 204:
            current_time = datetime.now().strftime("%Y-%m-%d %I:%M %p")
            
            log_data = {
                "embeds": [{
                    "title": "📋 سجل منح الرتب",
                    "color": 3066993,
                    "fields": [
                        {"name": "المسؤول", "value": admin_name, "inline": True},
                        {"name": "العضو", "value": f"<@{discord_id}>", "inline": True},
                        {"name": "الرتبة", "value": role_name, "inline": True},
                        {"name": "⏰ الوقت", "value": current_time, "inline": False}
                    ],
                    "footer": {"text": "Internal Affairs"}
                }]
            }
            
            webhook_response = requests.post(WEBHOOK_URL, json=log_data)
            print(f"Webhook Response: {webhook_response.status_code}")
            
            return {'success': True, 'message': 'تم منح رتبة الديسكورد بنجاح'}
        else:
            error_data = role_response.json()
            error_msg = error_data.get('message', 'خطأ غير معروف')
            return {'success': False, 'message': f'فشل منح الرتبة: {error_msg}'}
            
    except Exception as e:
        print(f"Error in assign_discord_role: {str(e)}")
        return {'success': False, 'message': f'حدث خطأ: {str(e)}'}

def remove_discord_role(discord_id, role_type, admin_name):
    BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
    SERVER_ID = os.getenv("DISCORD_SERVER_ID")
    WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")
    
    role_ids = {
        'deputy': '1430189316411228182',
        'management': '1430198706740793416',
        'member': '1430189364121702541'
    }
    
    role_names = {
        'deputy': 'Deputy Of Internal Affairs',
        'management': 'Internal Affairs Management', 
        'member': 'Internal Affairs Member'
    }
    
    role_id = role_ids.get(role_type)
    role_name = role_names.get(role_type)
    
    if not role_id:
        return {'success': False, 'message': 'نوع الرتبة غير صحيح'}
    
    headers = {
        "Authorization": f"Bot {BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    
    try:
        guild_url = f"https://discord.com/api/v10/guilds/{SERVER_ID}"
        guild_response = requests.get(guild_url, headers=headers)
        if guild_response.status_code != 200:
            return {'success': False, 'message': 'البوت لا يستطيع الوصول للسيرفر'}
        
        role_url = f"https://discord.com/api/v10/guilds/{SERVER_ID}/members/{discord_id}/roles/{role_id}"
        role_response = requests.delete(role_url, headers=headers)
        
        print(f"Discord API Response: {role_response.status_code}")
        
        if role_response.status_code == 204:
            current_time = datetime.now().strftime("%Y-%m-%d %I:%M %p")
            
            log_data = {
                "embeds": [{
                    "title": "📋 سجل سحب الرتب",
                    "color": 15158332,
                    "fields": [
                        {"name": "المسؤول", "value": admin_name, "inline": True},
                        {"name": "العضو", "value": f"<@{discord_id}>", "inline": True},
                        {"name": "الرتبة", "value": role_name, "inline": True},
                        {"name": "⏰ الوقت", "value": current_time, "inline": False}
                    ],
                    "footer": {"text": "Internal Affairs"}
                }]
            }
            
            webhook_response = requests.post(WEBHOOK_URL, json=log_data)
            print(f"Webhook Response: {webhook_response.status_code}")
            
            return {'success': True, 'message': 'تم سحب رتبة الديسكورد بنجاح'}
        else:
            error_data = role_response.json()
            error_msg = error_data.get('message', 'خطأ غير معروف')
            return {'success': False, 'message': f'فشل سحب الرتبة: {error_msg}'}
            
    except Exception as e:
        print(f"Error in remove_discord_role: {str(e)}")
        return {'success': False, 'message': f'حدث خطأ: {str(e)}'}

@login_required(login_url='ialogin')
def statistics(request):
    user_privs = get_detailed_privileges(request.user.id, 'النقاط')
    
    if user_privs.get('الوصول', 0) != 1:
        return render(request, "pages/access_denied.html")

    user_forms = get_user_forms(request.user.id)
    
    with connection.cursor() as cursor:
        cursor.execute("SELECT points FROM auth_user WHERE id = %s", [request.user.id])
        result = cursor.fetchone()
        user_points = result[0] if result else 0
        
        cursor.execute("""
            SELECT COUNT(*) + 1 FROM auth_user 
            WHERE points > (SELECT points FROM auth_user WHERE id = %s)
        """, [request.user.id])
        result = cursor.fetchone()
        user_rank = result[0] if result else 1
        
        cursor.execute("SELECT COUNT(*) FROM auth_user")
        result = cursor.fetchone()
        total_users = result[0] if result else 0
        
        cursor.execute("SELECT id, username, points FROM auth_user ORDER BY points DESC")
        columns = [col[0] for col in cursor.description]
        all_users = [dict(zip(columns, row)) for row in cursor.fetchall()]

    if request.method == "POST":
        action = request.POST.get('action')
        
        if action == 'update_points':
            operation_type = request.POST.get('operation_type')
            user_id = request.POST.get('user_id')
            points = int(request.POST.get('points', 0))
            reason = request.POST.get('reason', '')
            
            if operation_type  == 'add' and user_privs.get('منح نقاط', 0) != 1:
                return JsonResponse({'success': False, 'message': 'لا تملك صلاحية منح النقاط'})
            elif operation_type == 'subtract' and user_privs.get('خصم نقاط', 0) != 1:
                return JsonResponse({'success': False, 'message': 'لا تملك صلاحية خصم النقاط'})
            elif operation_type == 'decrease' and user_privs.get('تصغير نقاط', 0) != 1:
                return JsonResponse({'success': False, 'message': 'لا تملك صلاحية تصغير النقاط'})
            
            try:
                with connection.cursor() as cursor:
                    if operation_type == 'add':
                        cursor.execute("UPDATE auth_user SET points = points + %s WHERE id = %s", [points, user_id])
                        action_text = "إضافة"
                    elif operation_type == 'subtract':
                        cursor.execute("UPDATE auth_user SET points = points - %s WHERE id = %s", [points, user_id])
                        action_text = "خصم"
                    elif operation_type == 'decrease':
                        cursor.execute("UPDATE auth_user SET points = points - %s WHERE id = %s", [points, user_id])
                        action_text = "تصغير"
                    
                    cursor.execute("SELECT username FROM auth_user WHERE id = %s", [user_id])
                    username_result = cursor.fetchone()
                    username = username_result[0] if username_result else "مستخدم"
                    
                return JsonResponse({
                    'success': True, 
                    'message': f'تم {action_text} {points} نقطة للمستخدم {username} بنجاح'
                })
            except Exception as e:
                return JsonResponse({'success': False, 'message': f'حدث خطأ: {str(e)}'})
        
        elif action == 'reset_points':
            if user_privs.get('تصفير نقاط', 0) != 1:
                return JsonResponse({'success': False, 'message': 'لا تملك صلاحية تصفير النقاط'})
                
            user_id = request.POST.get('user_id')
            try:
                with connection.cursor() as cursor:
                    cursor.execute("UPDATE auth_user SET points = 0 WHERE id = %s", [user_id])
                    cursor.execute("SELECT username FROM auth_user WHERE id = %s", [user_id])
                    username_result = cursor.fetchone()
                    username = username_result[0] if username_result else "مستخدم"
                
                return JsonResponse({
                    'success': True, 
                    'message': f'تم تصفير نقاط المستخدم {username} بنجاح'
                })
            except Exception as e:
                return JsonResponse({'success': False, 'message': f'حدث خطأ: {str(e)}'})
        
        elif action == 'bulk_points':
            bulk_operation = request.POST.get('bulk_operation')
            bulk_reason = request.POST.get('bulk_reason', '')
            
            # التحقق من الصلاحيات
            if bulk_operation == 'add_all' and user_privs.get('منح نقاط', 0) != 1:
                return JsonResponse({'success': False, 'message': 'لا تملك صلاحية منح النقاط'})
            elif bulk_operation == 'reset_all' and user_privs.get('تصفير نقاط', 0) != 1:
                return JsonResponse({'success': False, 'message': 'لا تملك صلاحية تصفير النقاط'})
            
            try:
                with connection.cursor() as cursor:
                    if bulk_operation == 'add_all':
                        bulk_points = int(request.POST.get('bulk_points', 0))
                        cursor.execute("UPDATE auth_user SET points = points + %s", [bulk_points])
                        action_text = f"إضافة {bulk_points} نقطة للجميع"
                    elif bulk_operation == 'reset_all':
                        cursor.execute("UPDATE auth_user SET points = 0")
                        action_text = "تصفير نقاط الجميع"
                    
                return JsonResponse({
                    'success': True, 
                    'message': f'تم {action_text} بنجاح'
                })
            except Exception as e:
                return JsonResponse({'success': False, 'message': f'حدث خطأ: {str(e)}'})

    context = {
        'user_points': user_points,
        'user_rank': user_rank,
        'total_users': total_users,
        'all_users': all_users,
        'forms': user_forms,
        'user_privs': user_privs,
        'can_give_points': user_privs.get('منح نقاط', 0) == 1,
        'can_rem_points': user_privs.get('خصم نقاط', 0) == 1,
        'can_decrease_points': user_privs.get('تصغير نقاط', 0) == 1,
        'can_reset_points': user_privs.get('تصفير نقاط', 0) == 1,
        'can_bulk_actions': user_privs.get('زر إجراءات جماعية', 0) == 1,
        'can_remove_everyone': user_privs.get('تصفير الجميع', 0) == 1,
        'can_add_everyone': user_privs.get('إضافة للجميع', 0) == 1,
    }
    
    return render(request, "pages/statistics.html", context)

@login_required(login_url='ialogin')
def user_privileges_list(request):
    user_privs = get_detailed_privileges(request.user.id, 'الإدارة')
    
    if user_privs.get('الوصول', 0) != 1:
        return render(request, "pages/access_denied.html")

    query = """
        SELECT
            au.id,
            au.username,
            au.email,
            COALESCE(COUNT(up.priv_id), 0) AS privilege_count
        FROM
            auth_user au
        LEFT JOIN
            user_priv up ON au.id = up.user AND up.status = 1
        GROUP BY
            au.id, au.username, au.email
        ORDER BY
            au.id
    """
    
    with connection.cursor() as cursor:
        cursor.execute(query)
        columns = [col[0] for col in cursor.description]
        users = [dict(zip(columns, row)) for row in cursor.fetchall()]

    user_forms = get_user_forms(request.user.id)
    
    context = {
        'users': users,
        'forms': user_forms,
        'user_privs': user_privs,
        'can_manage': user_privs.get('إدارة', 0) == 1,
    }
    return render(request, "pages/user_list.html", context)

@login_required(login_url='ialogin')
def manage_privileges(request, user_id):
    user_privs = get_detailed_privileges(request.user.id, 'الإدارة')
    
    if user_privs.get('الوصول', 0) != 1 or user_privs.get('إدارة', 0) != 1:
        return render(request, "pages/access_denied.html")

    if request.method == 'GET':
        with connection.cursor() as cursor:
            cursor.execute("SELECT form_id, form_name, title FROM forms")
            forms = cursor.fetchall()
            
            permissions_data = []
            
            for form in forms:
                form_id, form_name, title = form
                
                cursor.execute("""
                    SELECT DISTINCT p.priv_id, p.priv_name, 
                           CASE WHEN up.status IS NULL THEN 0 ELSE up.status END as has_permission
                    FROM privilage p
                    LEFT JOIN user_priv up ON p.priv_id = up.priv_id AND up.user = %s
                    WHERE p.form_id = %s
                    ORDER BY p.priv_id
                """, [user_id, form_id])
                
                form_permissions = cursor.fetchall()
                
                if form_permissions:
                    permissions_data.append({
                        'form_id': form_id,
                        'form_name': form_name,
                        'title': title,
                        'permissions': [
                            {
                                'priv_id': perm[0],
                                'priv_name': perm[1],
                                'has_permission': bool(perm[2])
                            }
                            for perm in form_permissions
                        ]
                    })
            
            cursor.execute("SELECT id, username FROM auth_user WHERE id = %s", [user_id])
            user = cursor.fetchone()
        
        user_forms = get_user_forms(request.user.id)
        
        context = {
            'user_to_manage': {'id': user[0], 'username': user[1]} if user else None,
            'permissions_data': permissions_data,
            'forms': user_forms,
            'user_privs': user_privs,
            'can_manage': user_privs.get('إدارة', 0) == 1,
        }
        return render(request, "pages/manage_privileges.html", context)

@login_required(login_url='ialogin')
@require_http_methods(["POST"])
@csrf_exempt
def update_privilege(request):
    user_privs = get_detailed_privileges(request.user.id, 'الإدارة')
    
    if user_privs.get('إدارة', 0) != 1:
        return JsonResponse({'success': False, 'message': 'لا تملك صلاحية إدارة الصلاحيات.'})
    
    try:
        data = json.loads(request.body)
        user_id = data.get('user_id')
        priv_id = data.get('priv_id')
        is_checked = data.get('is_checked')
        
        if not all([user_id, priv_id]):
            return JsonResponse({'success': False, 'message': 'بيانات غير كاملة.'}, status=400)

        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) FROM user_priv
                    WHERE user = %s AND priv_id = %s
                """, [user_id, priv_id])

                exists = cursor.fetchone()[0] > 0

                if exists:
                    cursor.execute("""
                        UPDATE user_priv
                        SET status = %s
                        WHERE user = %s AND priv_id = %s
                    """, [1 if is_checked else 0, user_id, priv_id])
                else:
                    cursor.execute("""
                        INSERT INTO user_priv (user, priv_id, status)
                        VALUES (%s, %s, %s)
                    """, [user_id, priv_id, 1 if is_checked else 0])
                
                return JsonResponse({'success': True, 'message': 'تم تحديث الصلاحية بنجاح'})
                
        except Exception as e:
            return JsonResponse({'success': False, 'message': f'خطأ في قاعدة البيانات: {str(e)}'})

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'صيغة JSON غير صالحة.'}, status=400)
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'خطأ: {str(e)}'}, status=500)

def check_user_permission(request):
    if request.user.is_authenticated:
        user_id = request.user.id
        priv_id = request.GET.get('priv_id')
        
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT status FROM user_priv
                WHERE user = %s AND priv_id = %s AND status = 1
            """, [user_id, priv_id])
            
            has_permission = cursor.fetchone() is not None
            
        return JsonResponse({'has_permission': has_permission})
    
    return JsonResponse({'has_permission': False})

@login_required(login_url='ialogin')
@require_http_methods(["POST"])
@csrf_exempt
def soft_delete_report(request, report_id):
    user_privs = get_detailed_privileges(request.user.id, 'البلاغات')
    
    if user_privs.get('الحذف', 0) != 1:
        return JsonResponse({'success': False, 'message': 'لا تملك صلاحية حذف البلاغات.'})
    
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM reports WHERE id = %s AND perm = 0", [report_id])
            report_exists = cursor.fetchone()
            
            if not report_exists:
                return JsonResponse({'success': False, 'message': 'البلاغ غير موجود أو محذوف نهائياً.'})
            
            cursor.execute(
                "UPDATE reports SET is_deleted = 1 WHERE id = %s AND perm = 0", 
                [report_id]
            )
            
        return JsonResponse({'success': True, 'message': 'تم حذف البلاغ بنجاح.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'حدث خطأ أثناء حذف البلاغ: {str(e)}'})

@login_required(login_url='ialogin')
def iareport(request):
    user_privs = get_detailed_privileges(request.user.id, 'البلاغات')
    
    if user_privs.get('الوصول', 0) != 1:
        return render(request, "pages/access_denied.html")

    with connection.cursor() as cursor:
        active_query = """
            SELECT 
                r.id, r.name, r.content, r.evidence_url, r.status, r.is_deleted, r.perm,
                u.username as closed_by_username
            FROM 
                reports r
            LEFT JOIN 
                auth_user u ON r.closed_by_id = u.id
            WHERE r.is_deleted = 0 AND r.perm = 0    
            ORDER BY 
                r.status ASC, r.id DESC
        """
        cursor.execute(active_query)
        columns = [col[0] for col in cursor.description]
        active_reports = [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        deleted_reports = []
        deleted_reports_count = 0
        if user_privs.get('عرض المحذوفه', 0) == 1:
            deleted_query = """
                SELECT 
                    r.id, r.name, r.content, r.evidence_url, r.status, r.is_deleted, r.perm,
                    u.username as closed_by_username
                FROM 
                    reports r
                LEFT JOIN 
                    auth_user u ON r.closed_by_id = u.id
                WHERE r.is_deleted = 1 AND r.perm = 0    
                ORDER BY r.id DESC
            """
            cursor.execute(deleted_query)
            deleted_reports = [dict(zip(columns, row)) for row in cursor.fetchall()]
            deleted_reports_count = len(deleted_reports)
        
        pending_count = len([r for r in active_reports if r['status'] == 0])
        completed_count = len([r for r in active_reports if r['status'] == 1])
        active_count = len(active_reports)
        
    user_forms = get_user_forms(request.user.id)

    context = {
        'reports': active_reports + deleted_reports,
        'active_reports_count': active_count,
        'pending_reports_count': pending_count,
        'completed_reports_count': completed_count,
        'deleted_reports_count': deleted_reports_count,
        'forms': user_forms,
        'user_privs': user_privs,
        'can_handle': user_privs.get('التعامل', 0) == 1,
        'can_delete_report': user_privs.get('الحذف', 0) == 1,
        'can_view_deleted': user_privs.get('عرض المحذوفه', 0) == 1,
        'can_restore': user_privs.get('إستعادة بلاغ', 0) == 1,
        'can_see': user_privs.get('مشاهدة الدلائل', 0) == 1,
        'can_permanent_delete': user_privs.get('حذف نهائي', 0) == 1,
    }
    
    if request.method == "POST":
        report_id = request.POST.get('report_id')
        
        if 'mark_done' in request.POST:
            if user_privs.get('التعامل', 0) != 1:
                messages.error(request, 'لا تملك صلاحية التعامل مع البلاغات.')
                return redirect('iareport')
                
            current_user_id = request.user.id 
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE reports SET status = TRUE, closed_by_id = %s WHERE id = %s AND is_deleted = 0 AND perm = 0", 
                    [current_user_id, report_id]
                )
                cursor.execute(
                    "UPDATE auth_user SET points = points + 5 WHERE id = %s", 
                    [current_user_id]
                )
            messages.success(request, 'تم التعامل مع أخر بلاغ  .')
            return redirect('iareport')
            
        elif 'delete_report' in request.POST:
            if user_privs.get('الحذف', 0) != 1:
                messages.error(request, 'لا تملك صلاحية حذف البلاغات.')
                return redirect('iareport')
                
            try:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "UPDATE reports SET is_deleted = 1 WHERE id = %s AND perm = 0", 
                        [report_id]
                    )
                messages.success(request, 'تم حذف البلاغ بنجاح.')
            except Exception as e:
                messages.error(request, f'حدث خطأ أثناء حذف البلاغ: {str(e)}')
            return redirect('iareport')
    
    return render(request, "pages/reports.html", context)

@login_required(login_url='ialogin')
@require_http_methods(["POST"])
@csrf_exempt
@login_required(login_url='ialogin')
@require_http_methods(["POST"])
@csrf_exempt
def restore_report(request, report_id):
    user_privs = get_detailed_privileges(request.user.id, 'البلاغات')
    
    if user_privs.get('إستعادة بلاغ', 0) != 1:
        return JsonResponse({'success': False, 'message': 'لا تملك صلاحية استعادة البلاغات.'})
    
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT id FROM reports WHERE id = %s AND perm = 0", [report_id])
            report_exists = cursor.fetchone()
            
            if not report_exists:
                return JsonResponse({'success': False, 'message': 'البلاغ غير موجود أو محذوف نهائياً.'})
            
            cursor.execute(
                "UPDATE reports SET is_deleted = 0 WHERE id = %s AND perm = 0", 
                [report_id]
            )
        return JsonResponse({'success': True, 'message': 'تم استعادة البلاغ بنجاح.'})
    except Exception as e:
        return JsonResponse({'success': False, 'message': f'حدث خطأ أثناء استعادة البلاغ: {str(e)}'})
    
@login_required(login_url='ialogin')
def home(request):

    user_forms = get_user_forms(request.user.id)
 
    context = {
         'forms': user_forms,
    }
    return render(request, "pages/home.html", context)


def logout_view(request):
    logout(request)
    return redirect("ialogin")