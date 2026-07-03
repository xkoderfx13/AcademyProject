from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponseForbidden
from django.contrib.auth.hashers import make_password, check_password
from .models import User, Assignment, Evaluation, Message, Notification, Application, Question, TestSession, ApplicantAnswer, ApplicationSetting, AuditLog, AuditTemplate
from django.db import IntegrityError
from django.db.models import Q
from django.db import models
from django.views.decorators.csrf import csrf_exempt
import os
from django.utils import timezone
import datetime
import logging
from django.views.decorators.http import require_POST
import random
import secrets
import requests
import json
from urllib.parse import urlencode
from django.conf import settings


# --- Helpers ---
def get_session_user(request):
    uid = request.session.get('uid')
    if not uid:
        return None
    try:
        return User.objects.get(id=uid)
    except User.DoesNotExist:
        return None

def role_required(roles):
    """Deprecated - use rank_required instead"""
    def decorator(view_func):
        def _wrapped_view(request, *args, **kwargs):
            user = get_session_user(request)
            if not user or user.rank not in roles:
                return redirect('login')
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator

def rank_required(min_rank=None, dashboard_only=False, applications_only=False):
    """Decorator to check user rank and dashboard access"""
    def decorator(view_func):
        def _wrapped_view(request, *args, **kwargs):
            user = get_session_user(request)
            if not user:
                return redirect('login')
            
            # Check dashboard access
            if dashboard_only and not user.has_dashboard_access():
                return render(request, 'error.html', {'message': 'You do not have access to admin dashboard.'})
            
            # Check applications access
            if applications_only and not user.can_view_applications():
                return render(request, 'error.html', {'message': 'You do not have access to applications.'})
            
            # Check minimum rank if specified
            if min_rank and user.get_rank_hierarchy() < User.RANK_HIERARCHY.get(min_rank, 0):
                return render(request, 'error.html', {'message': f'You need at least {min_rank} rank.'})
            
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator

# --- Auth ---
def login_view(request):
    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        try:
            user = User.objects.get(username=u)
            # Check password (supporting both plain for legacy and hashed for new)
            password_valid = False
            try:
                password_valid = check_password(p, user.password)
            except:
                password_valid = (p == user.password)
            
            if password_valid or p == user.password:
                request.session['uid'] = user.id
                request.session['rank'] = user.rank
                request.session['name'] = user.full_name
                
                # Upgrade password to hash if it was plain
                if p == user.password and not user.password.startswith('pbkdf2_'):
                    user.set_password(p)
                    user.save()
                
                # audit successful login
                try:
                    _audit_log('login', user, target=f'user:{user.id}', details='successful login')
                except Exception:
                    pass
                
                # Redirect based on rank
                if user.has_dashboard_access(): 
                    return redirect('admin_dashboard')
                elif user.rank == 'trainer': 
                    return redirect('trainer_dashboard')
                else:  # cadet
                    return redirect('cadet_dashboard')
            else:
                return render(request, 'login.html', {'error': 'بيانات الدخول غير صحيحة'})
        except User.DoesNotExist:
            return render(request, 'login.html', {'error': 'المستخدم غير موجود'})
        except Exception as e:
            return render(request, 'login.html', {'error': f'خطأ في النظام: {str(e)}'})
    return render(request, 'login.html')

def logout_view(request):
    user = get_session_user(request)
    try:
        _audit_log('logout', user, target=f'user:{user.id}' if user else '', details='user logout')
    except Exception:
        pass
    request.session.flush()
    return redirect('login')

# --- Dashboards ---
@rank_required(dashboard_only=True)
def admin_dashboard(request):
    actor = get_session_user(request)
    
    # Admin (dev and higher) see all users, others see only manageable
    if actor.rank == 'dev':  # Dev can see all users
        users = User.objects.all().order_by('rank', 'username')
    else:
        # Show only users with ranks the actor can manage
        manageable_ranks = actor.get_manageable_ranks()
        users = User.objects.filter(rank__in=manageable_ranks).order_by('rank', 'username')
    
    return render(request, 'admin_dashboard.html', {'users': users, 'actor': actor})

@rank_required(dashboard_only=True)
def admin_member_detail(request, uid):
    actor = get_session_user(request)
    target_user = get_object_or_404(User, id=uid)
    
    # Check if actor can view this user's details
    if not actor.can_manage_user(target_user):
        return render(request, 'error.html', {'message': 'ليس لديك صلاحيات لعرض تفاصيل هذا المستخدم.'})
    
    if target_user.rank == 'trainer':
        evals = Evaluation.objects.filter(trainer=target_user).select_related('cadet')
    elif target_user.rank == 'cadet':
        evals = Evaluation.objects.filter(cadet=target_user).select_related('trainer')
    else:
        evals = []

    # Get Chat History - organize by conversation partner
    all_messages = Message.objects.filter(
        models.Q(sender=target_user) | models.Q(receiver=target_user)
    ).select_related('sender', 'receiver').order_by('created_at')
    
    # Group messages by conversation partner
    chats_dict = {}
    for msg in all_messages:
        # Determine the other person in the conversation
        other_user = msg.receiver if msg.sender == target_user else msg.sender
        
        if other_user.id not in chats_dict:
            chats_dict[other_user.id] = {
                'other': other_user,
                'messages': []
            }
        
        chats_dict[other_user.id]['messages'].append({
            'sender_id': msg.sender.id,
            'content': msg.content,
            'timestamp': msg.created_at
        })
    
    # Convert to list
    chats = list(chats_dict.values())
    
    if request.method == 'POST':
        msg_content = request.POST.get('message')
        Notification.objects.create(user=target_user, message=msg_content)
        return redirect('admin_member_detail', uid=uid)

    return render(request, 'admin_member_detail.html', {
        'target': target_user, 
        'evaluations': evals,
        'chats': chats
    })

@role_required(['trainer'])
def trainer_dashboard(request):
    user = get_session_user(request)
    assignments = Assignment.objects.filter(trainer=user).select_related('cadet')
    
    # Get cadets with unread message counts
    cadets_data = []
    for a in assignments:
        unread_count = Message.objects.filter(
            sender=a.cadet,
            receiver=user,
            is_read=False
        ).count()
        cadets_data.append({
            'cadet': a.cadet,
            'unread_count': unread_count
        })
    
    notifs = Notification.objects.filter(user=user, is_read=False)
    return render(request, 'trainer_dashboard.html', {
        'cadets_data': cadets_data,
        'user': user,
        'notifications': notifs
    })

@role_required(['cadet'])
def cadet_dashboard(request):
    user = get_session_user(request)
    assignments = Assignment.objects.filter(cadet=user).select_related('trainer')
    
    # Get trainers with unread message counts
    trainers_data = []
    for a in assignments:
        unread_count = Message.objects.filter(
            sender=a.trainer,
            receiver=user,
            is_read=False
        ).count()
        trainers_data.append({
            'trainer': a.trainer,
            'unread_count': unread_count
        })
    
    notifications = Notification.objects.filter(user=user, is_read=False).order_by('-created_at')
    return render(request, 'cadet_dashboard.html', {
        'user': user,
        'trainers_data': trainers_data,
        'notifications': notifications
    })

# --- Admin CRUD ---
@rank_required(dashboard_only=True)
def admin_add_user(request):
    actor = get_session_user(request)
    
    # Check if user can add users
    if not actor.can_add_users():
        return render(request, 'error.html', {'message': 'ليس لديك صلاحيات لإضافة مستخدمين.'})
    
    if request.method == 'POST':
        u = request.POST.get('username')
        p = request.POST.get('password')
        fn = request.POST.get('full_name')
        rank = request.POST.get('rank')
        
        # Check if the rank is manageable by current user
        if rank not in actor.get_manageable_ranks():
            return render(request, 'user_form.html', {
                'title': 'إضافة مستخدم',
                'error': f'لا يمكنك إضافة مستخدم برتبة {rank}. الرتب المسموح بها: {", ".join(actor.get_manageable_ranks())}'
            })
        
        try:
            user = User(username=u, full_name=fn, rank=rank)
            user.set_password(p)
            user.save()
            try:
                _audit_log('admin_add_user', actor, target=f'user:{user.id}', details=f'created user {user.username} with rank {rank}')
            except Exception:
                pass
            return redirect('admin_dashboard')
        except IntegrityError:
            return render(request, 'user_form.html', {'title': 'إضافة مستخدم', 'error': 'اسم المستخدم موجود مسبقاً'})
    
    # Only show ranks the current user can manage
    available_ranks = actor.get_manageable_ranks()
    return render(request, 'user_form.html', {
        'title': 'إضافة مستخدم',
        'actor': actor,
        'available_ranks': available_ranks,
        'rank_choices': [r for r in User.RANK_CHOICES if r[0] in available_ranks]
    })

@rank_required(dashboard_only=True)
def admin_edit_user(request, uid):
    actor = get_session_user(request)
    user = get_object_or_404(User, id=uid)
    
    # Check if actor can manage this user
    if not actor.can_manage_user(user):
        return render(request, 'error.html', {'message': 'ليس لديك صلاحيات لتعديل هذا المستخدم.'})
    
    if request.method == 'POST':
        p = request.POST.get('password')
        fn = request.POST.get('full_name')
        new_rank = request.POST.get('rank')
        
        # Check if trying to change rank to something unmanageable
        if new_rank and new_rank != user.rank and new_rank not in actor.get_manageable_ranks():
            return render(request, 'user_form.html', {
                'title': 'تعديل مستخدم',
                'edit_user': user,
                'error': f'لا يمكنك تعديل الرتبة إلى {new_rank}. الرتب المسموح بها: {", ".join(actor.get_manageable_ranks())}'
            })
        
        user.full_name = fn
        if new_rank and new_rank in actor.get_manageable_ranks():
            user.rank = new_rank
        if p:
            user.set_password(p)
        user.save()
        try:
            _audit_log('admin_edit_user', actor, target=f'user:{user.id}', details=f'edited user {user.username}')
        except Exception:
            pass
        return redirect('admin_dashboard')
    
    available_ranks = actor.get_manageable_ranks()
    return render(request, 'user_form.html', {
        'title': 'تعديل مستخدم',
        'edit_user': user,
        'actor': actor,
        'available_ranks': available_ranks,
        'rank_choices': [r for r in User.RANK_CHOICES if r[0] in available_ranks]
    })

@rank_required(dashboard_only=True)
def admin_delete_user(request, uid):
    actor = get_session_user(request)
    user = get_object_or_404(User, id=uid)
    
    # Check if actor can manage this user
    if not actor.can_manage_user(user):
        return render(request, 'error.html', {'message': 'ليس لديك صلاحيات لحذف هذا المستخدم.'})
    
    uname = user.username
    uid_val = user.id
    user.delete()
    try:
        _audit_log('admin_delete_user', actor, target=f'user:{uid_val}', details=f'deleted user {uname}')
    except Exception:
        pass
    return redirect('admin_dashboard')

@rank_required(dashboard_only=True)
def admin_assignments_view(request):
    actor = get_session_user(request)
    
    # Check if user can manage assignments
    if not actor.can_manage_assignments():
        return render(request, 'error.html', {'message': 'ليس لديك صلاحيات لإدارة التعيينات.'})
    
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'assign':
            tid = request.POST.get('trainer_id')
            cid = request.POST.get('cadet_id')
            trainer = get_object_or_404(User, id=tid)
            cadet = get_object_or_404(User, id=cid)
            Assignment.objects.get_or_create(trainer=trainer, cadet=cadet)
            try:
                actor = get_session_user(request)
                details = f'trainer {trainer.username} To cadet{cadet.id}'
                _audit_log('assign_trainer', actor, target=f'assignment:{trainer.id}-{cadet.id}', details=details)
            except Exception:
                pass
        elif action == 'delete':
            aid = request.POST.get('assignment_id')
            assignment = Assignment.objects.filter(id=aid).first()
            if assignment:
                trainer = assignment.trainer
                cadet = assignment.cadet
                assignment.delete()
                details = f'trainer {trainer.username} To cadet{cadet.id}'
                target = f'assignment:{trainer.id}-{cadet.id}'
            else:
                Assignment.objects.filter(id=aid).delete()
                details = f'assignment:{aid}'
                target = f'assignment:{aid}'
            try:
                actor = get_session_user(request)
                _audit_log('delete_assignment', actor, target=target, details=details)
            except Exception:
                pass
        return redirect('admin_assignments')

    trainers = User.objects.filter(rank='trainer')
    cadets = User.objects.filter(rank='cadet')
    assignments = Assignment.objects.all().select_related('trainer', 'cadet')
    return render(request, 'assignments.html', {'trainers': trainers, 'cadets': cadets, 'assignments': assignments})

# --- Features ---
from django.utils import timezone
import json
import re
from . import discord_utils

logger = logging.getLogger(__name__)


def _audit_log(action, actor_user, target='', details=''):
    try:
        AuditLog.objects.create(actor=actor_user, action=action, target=target, details=details)
    except Exception:
        pass
    
    try:
        ch = os.getenv('DISCORD_LOG_CHANNEL_ID', '1446744094952128733')
        if not ch:
            return
        
        # دالة مساعدة لإنشاء Discord mention
        def create_discord_mention(user_obj):
            if not user_obj:
                return "النظام"
            
            # إذا كان لدى المستخدم discord_id
            if hasattr(user_obj, 'discord_id') and user_obj.discord_id:
                # استخراج الأرقام فقط
                numbers = re.findall(r'\d+', str(user_obj.discord_id))
                if numbers:
                    return f"<@{numbers[0]}>"
            
            # استخدم username كبديل
            return f"@{getattr(user_obj, 'username', 'مستخدم')}"
        
        # منشن للمستخدم الفاعل
        actor_mention = create_discord_mention(actor_user)
        
        # إيموجيات وأسماء
        emojis = {
            'prelim_accept': '✅', 'final_accept': '🎯', 'reject': '❌',
            'apply_submit': '📝', 'evaluate': '⭐', 'login': '🔓',
            'logout': '🔒', 'admin_add_user': '➕', 'assign_trainer': '👥',
            'send_dm_custom': '💬'
        }
        
        action_names = {
            'prelim_accept': 'قبول مبدئي',
            'final_accept': 'قبول نهائي',
            'reject': 'رفض',
            'apply_submit': 'تقديم جديد',
            'evaluate': 'تقييم',
            'login': 'تسجيل دخول',
            'logout': 'تسجيل خروج',
            'admin_add_user': 'إضافة مستخدم',
            'assign_trainer': 'تعيين',
            'open_all': 'فتح التقديم',
            'close_with_message_global': 'إغلاق مع رسالة',
            'close_with_timer_global': 'إغلاق مع مؤقت',
            'delete_assignment': 'حذف تعيين',
            'admin_edit_user': 'تعديل معلومات مستخدم',
            'admin_delete_user': 'حذف مستخدم',
            'send_dm_custom': 'رسالة خاصة',
            'hide': 'إخفاء طلب',
            'start_test': 'بدء الاختبار',
            'finish_test': 'انتهى من الاختبار',
        }
        
        emoji = emojis.get(action, '📌')
        title = action_names.get(action, action)
        
        # رسائل بسيطة مع منشن
        if action == 'prelim_accept':
            # استخراج Discord ID من التفاصيل
            discord_match = re.search(r'\(([0-9]+)\)', details)
            applicant_mention = f"<@{discord_match.group(1)}>" if discord_match else "متدرب"
            message = f"{emoji} **{title}** - {actor_mention} → {applicant_mention}"
        
        elif action == 'final_accept':
            discord_match = re.search(r'\(([0-9]+)\)', details)
            applicant_mention = f"<@{discord_match.group(1)}>" if discord_match else "متدرب"
            message = f"{emoji} **{title}** - {actor_mention} → {applicant_mention}"
        
        elif action == 'reject':
            discord_match = re.search(r'\(([0-9]+)\)', details)
            applicant_mention = f"<@{discord_match.group(1)}>" if discord_match else "متدرب"
            message = f"{emoji} **{title}** - {actor_mention} → {applicant_mention}"
        
        elif action == 'apply_submit':
            # أخذ Discord ID من التفاصيل مباشرة
            discord_match = re.search(r'by discord ([0-9]+)', details)
            applicant_mention = f"<@{discord_match.group(1)}>" if discord_match else "مستخدم"
            message = f"{emoji} **{title}** - {applicant_mention}"
        
        elif action == 'evaluate':
            # محاولة استخراج Discord ID للمتدرب من الـ target
            cadet_id_match = re.search(r'cadet:(\d+)', target)
            if cadet_id_match:
                try:
                    cadet = User.objects.get(id=cadet_id_match.group(1))
                    cadet_mention = create_discord_mention(cadet)
                except:
                    cadet_mention = "متدرب"
            else:
                cadet_mention = "متدرب"
            
            message = f"{emoji} **{title}** - {actor_mention} → {cadet_mention}"
        
        else:
            message = f"{emoji} **{title}** - {actor_mention}"
        
        discord_utils.send_channel_message(ch, message)
        
    except Exception:
        pass


def _parse_reopen_dt(dt_str):
    """Parse various reopen_at formats from POST and return timezone-aware datetime or None."""
    if not dt_str:
        return None
    try:
        # epoch seconds
        if dt_str.isdigit():
            return datetime.datetime.fromtimestamp(int(dt_str), tz=datetime.timezone.utc)

        # ISO with offset or Z
        try:
            dt = datetime.datetime.fromisoformat(dt_str)
        except Exception:
            # try replacing space with T if needed
            try:
                dt = datetime.datetime.fromisoformat(dt_str.replace(' ', 'T'))
            except Exception:
                dt = None

        if dt:
            # if naive assume server timezone (convert to aware)
            if dt.tzinfo is None:
                try:
                    return timezone.make_aware(dt, timezone.get_current_timezone())
                except Exception:
                    return dt.replace(tzinfo=datetime.timezone.utc)
            return dt
    except Exception:
        return None
    return None

def chat_view(request, other_id):
    user = get_session_user(request)
    if not user: 
        return redirect('login')
    
    other = get_object_or_404(User, id=other_id)
    
    if not user.has_dashboard_access():
        is_assigned = Assignment.objects.filter(
            models.Q(trainer=user, cadet=other) | models.Q(trainer=other, cadet=user)
        ).exists()
        if not is_assigned:
            return HttpResponseForbidden("غير مسموح لك بمراسلة هذا المستخدم")

    if request.method == 'POST':
        content = request.POST.get('content', '').strip()
        if content:
            msg = Message.objects.create(
                sender=user, 
                receiver=other, 
                content=content
            )
            
            if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return JsonResponse({
                    'id': msg.id,
                    'content': msg.content,
                    'timestamp': msg.created_at.isoformat(),
                    'time': msg.created_at.strftime("%H:%M"),
                    'date': msg.created_at.strftime("%Y/%m/%d")
                })
            
            return redirect('chat', other_id=other_id)
    
    # إرسال timestamps مع الرسائل
    messages = Message.objects.filter(
        models.Q(sender=user, receiver=other) | 
        models.Q(sender=other, receiver=user)
    ).order_by('created_at')
    
    # Mark messages from other person as read
    Message.objects.filter(
        sender=other,
        receiver=user,
        is_read=False
    ).update(is_read=True)
    
    # تحويل الرسائل إلى قائمة مع timestamps
    messages_data = []
    for msg in messages:
        messages_data.append({
            'id': msg.id,
            'content': msg.content,
            'sender_id': msg.sender.id,
            'timestamp': msg.created_at.isoformat(),
            'time': msg.created_at.strftime("%H:%M"),
            'date': msg.created_at.strftime("%Y/%m/%d")
        })
    
    return render(request, 'chat.html', {
        'messages_json': json.dumps(messages_data),  # إرسال كـ JSON
        'messages': messages,
        'other': other, 
        'user': user,
        'my_id': user.id
    })

@csrf_exempt
def chat_messages_api(request, other_id):
    user = get_session_user(request)
    if not user:
        return JsonResponse({'error': 'Unauthorized'}, status=401)
    
    other = get_object_or_404(User, id=other_id)
    
    # Security Check
    if not user.has_dashboard_access():
        is_assigned = Assignment.objects.filter(
            models.Q(trainer=user, cadet=other) | models.Q(trainer=other, cadet=user)
        ).exists()
        if not is_assigned:
            return JsonResponse({'error': 'Forbidden'}, status=403)
    
    # الحصول على الرسائل الجديدة فقط
    last_id = request.GET.get('last_id', 0)
    try:
        last_id = int(last_id)
    except:
        last_id = 0
    
    messages = Message.objects.filter(
        (models.Q(sender=user, receiver=other) | models.Q(sender=other, receiver=user))
    ).filter(id__gt=last_id).order_by('created_at')
    
    messages_data = []
    for msg in messages:
        messages_data.append({
            'id': msg.id,
            'content': msg.content,
            'sender_id': msg.sender.id,
            'timestamp': msg.created_at.isoformat()  # تنسيق ISO الكامل
        })
    
    return JsonResponse({'messages': messages_data})


def question_api(request, qid):
    # Simple API to fetch a question by id
    q = get_object_or_404(Question, id=qid)
    return JsonResponse({'id': q.id, 'text': q.text, 'options': q.options()})


def apply_status_api(request):
    """Return JSON with current apply open/closed status and optional reopen_at epoch."""
    try:
        setting, _ = ApplicationSetting.objects.get_or_create(id=1)
    except Exception:
        setting = ApplicationSetting.objects.first()

    if setting:
        open_mode = (setting.status != 'closed')
        closed_message = setting.closed_message or ''
        reopen_at = int(setting.reopen_at.timestamp()) if setting.reopen_at else None
    else:
        open_mode = True
        closed_message = ''
        reopen_at = None

    return JsonResponse({'open': open_mode, 'closed_message': closed_message, 'reopen_at': reopen_at})


@role_required(['trainer'])
def evaluate_view(request, cadet_id):
    trainer = get_session_user(request)
    cadet = get_object_or_404(User, id=cadet_id)
    
    # Security Check: Ensure trainer is assigned to this cadet
    is_assigned = Assignment.objects.filter(trainer=trainer, cadet=cadet).exists()
    if not is_assigned:
        return HttpResponseForbidden("غير مسموح لك بتقييم متدرب غير تحت إشرافك")

    if request.method == 'POST':
        score = int(request.POST.get('score'))
        comment = request.POST.get('comment')
        
        Evaluation.objects.create(trainer=trainer, cadet=cadet, score=score, comments=comment)
        
        if score < 50:
            Notification.objects.create(
                user=cadet, 
                message=f"تنبيه: لقد حصلت على تقييم بدرجة ({score}) نأمل منك التطوير. في حال وجود أي استفسار تواصل مع المدرب."
            )
            
        try:
            actor = get_session_user(request)
            _audit_log('evaluate', actor, target=f'cadet:{cadet.id}', details=f'score={score} comments={comment}')
        except Exception:
            pass
        return redirect('trainer_dashboard')
        
    return render(request, 'evaluation_form.html', {'cadet': cadet})

def mark_read(request, nid):
    user = get_session_user(request)
    if not user: return JsonResponse({'status': 'error'}, status=403)
    
    notif = get_object_or_404(Notification, id=nid, user=user)
    notif.is_read = True
    notif.save()
    return JsonResponse({'status': 'ok'})

def get_unread_messages_count(request):
    user = get_session_user(request)
    if not user:
        return JsonResponse({'status': 'error'}, status=403)
    
    # Get unread messages grouped by sender
    from django.db.models import Count
    counts = Message.objects.filter(receiver=user, is_read=False).values('sender').annotate(count=Count('id'))
    
    unread_data = {item['sender']: item['count'] for item in counts}
        
    return JsonResponse({'counts': unread_data})


# --- Discord OAuth Views ---
def discord_oauth_login(request):
    """Redirect to Discord OAuth authorization page"""
    client_id = os.getenv('DISCORD_CLIENT_ID', '').strip()
    redirect_uri = request.build_absolute_uri('/apply/discord-callback/')
    
    if not client_id:
        request.session['error_message'] = 'Discord OAuth لم يتم تكوينه. تأكد من إضافة DISCORD_CLIENT_ID في ملف .env'
        return redirect('apply_page')
    
    # Discord OAuth2 authorization endpoint
    auth_url = 'https://discord.com/api/oauth2/authorize'
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'response_type': 'code',
        'scope': 'identify',
    }
    
    full_url = f"{auth_url}?{urlencode(params)}"
    return redirect(full_url)


def discord_oauth_callback(request):
    """Handle Discord OAuth callback"""
    code = request.GET.get('code')
    if not code:
        request.session['error_message'] = 'Failed to get authorization code from Discord'
        return redirect('apply_page')
    
    client_id = os.getenv('DISCORD_CLIENT_ID', '')
    client_secret = os.getenv('DISCORD_CLIENT_SECRET', '')
    redirect_uri = request.build_absolute_uri('/apply/discord-callback/')
    
    if not client_id or not client_secret:
        request.session['error_message'] = 'Discord OAuth not configured'
        return redirect('apply_page')
    
    # Exchange code for access token
    token_url = 'https://discord.com/api/oauth2/token'
    data = {
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'authorization_code',
        'code': code,
        'redirect_uri': redirect_uri,
    }
    
    try:
        response = requests.post(token_url, data=data, timeout=10)
        response.raise_for_status()
        token_data = response.json()
        access_token = token_data.get('access_token')
        
        if not access_token:
            request.session['error_message'] = 'Failed to get access token'
            return redirect('apply_page')
        
        # Get user info from Discord
        user_url = 'https://discord.com/api/users/@me'
        headers = {'Authorization': f'Bearer {access_token}'}
        user_response = requests.get(user_url, headers=headers, timeout=10)
        user_response.raise_for_status()
        user_data = user_response.json()
        
        discord_id = user_data.get('id')
        username = user_data.get('username', '')
        
        if not discord_id:
            request.session['error_message'] = 'Failed to get Discord ID'
            return redirect('apply_page')
        
        # Store Discord ID in session
        request.session['discord_id'] = discord_id
        request.session['discord_username'] = username
        
        # Redirect back to apply page
        return redirect('apply_page')
        
    except requests.RequestException as e:
        request.session['error_message'] = f'Failed to authenticate with Discord: {str(e)}'
        return redirect('apply_page')


# --- Apply & Test Views ---
def apply_page(request):
    # show apply form and open/closed status
    open_mode = True
    closed_message = ''
    reopen_at = None
    user_already_tested = False
    oauth_configured = bool(os.getenv('DISCORD_CLIENT_ID', '').strip())

    # وضع الاختبار المحلي: يسمح بإدخال Discord ID يدوياً عندما لا يكون OAuth مضبوطاً
    if request.method == 'POST' and settings.DEBUG and not oauth_configured:
        manual_id = request.POST.get('discord_id_manual', '').strip()
        if manual_id:
            request.session['discord_id'] = manual_id
            request.session['discord_username'] = manual_id
            return redirect('apply_page')

    # Check if user already submitted (by checking Discord ID from any previous Application)
    # Prevent same Discord ID from submitting more than once - ever
    if request.method == 'POST':
        discord_id = request.POST.get('discord_id', '').strip()
        if discord_id:
            existing_app = Application.objects.filter(discord_id=discord_id).first()
            if existing_app:
                user_already_tested = True
    
    # Prefer global ApplicationSetting if present (supports timed reopen)
    # Use singleton setting record (id=1) to avoid ambiguity between multiple rows
    try:
        setting, _ = ApplicationSetting.objects.get_or_create(id=1)
    except Exception:
        setting = None

    now = timezone.now()
    if setting:
        # auto-reopen if timer expired
        if setting.reopen_at and setting.reopen_at <= now:
            setting.status = 'open'
            setting.reopen_at = None
            setting.closed_message = ''
            setting.save()
            # reopen any applications that were closed by the global setting
            Application.objects.filter(status='closed').update(status='open', closed_message='', reopen_at=None)

        if setting.status == 'closed':
            open_mode = False
            closed_message = setting.closed_message or ''
            reopen_at = setting.reopen_at
    else:
        # fallback: determine global settings from DB: for simplicity use latest Application closed fields if any
        last_closed = Application.objects.filter(status='closed').order_by('-submitted_at').first()
        if last_closed:
            open_mode = False
            closed_message = last_closed.closed_message or ''
            reopen_at = last_closed.reopen_at
    
    if user_already_tested:
        open_mode = False
        closed_message = 'عذراً، هذا الرقم Discord قد قدّم بالفعل. يُسمح بمحاولة واحدة فقط لكل شخص.'

    # Get error message from session if exists
    error_message = request.session.pop('error_message', None)

    return render(request, 'apply.html', {
        'open': open_mode,
        'closed_message': closed_message,
        'reopen_at': reopen_at,
        'user_already_tested': user_already_tested,
        'error_message': error_message,
        'discord_id': request.session.get('discord_id'),
        'discord_username': request.session.get('discord_username'),
        'discord_oauth_configured': oauth_configured,
    })


@require_POST
def apply_submit(request):
    # Get Discord ID from session (set by OAuth callback)
    discord_id = request.session.get('discord_id')
    character = request.POST.get('character_name')
    
    if not discord_id or not character:
        return JsonResponse({'error': 'يرجى تسجيل الدخول عبر Discord أولاً'}, status=400)

    # Check if this Discord ID has already submitted (prevent duplicates)
    if Application.objects.filter(discord_id=discord_id.strip()).exists():
        return JsonResponse({'error': 'هذا الرقم Discord قد قدّم بالفعل. يُسمح بمحاولة واحدة فقط لكل شخص.'}, status=400)

    app = Application.objects.create(discord_id=discord_id.strip(), character_name=character.strip(), status='open')
    try:
        actor = get_session_user(request)
        _audit_log('apply_submit', actor, target=f'application:{app.id}', details=f'new application by discord {app.discord_id}')
    except Exception:
        pass
    return JsonResponse({'ok': True, 'app_id': app.id})


def apply_start_test(request, app_id):
    # create a TestSession with 10 random questions and redirect to test page
    app = get_object_or_404(Application, id=app_id)
    
    # Check if user already started test before (prevent re-attempts)
    if app.test_started_at is not None:
        return render(request, 'apply.html', {
            'open': False, 
            'closed_message': 'عذراً، لقد حاولت الاختبار بالفعل. يُسمح بمحاولة واحدة فقط.'
        })
    
    # check global setting as well
    # ensure we reference the singleton setting entry
    try:
        setting, _ = ApplicationSetting.objects.get_or_create(id=1)
    except Exception:
        setting = None
    if (app.status == 'closed') or (setting and setting.status == 'closed'):
        return render(request, 'apply.html', {'open': False, 'closed_message': setting.closed_message if setting else 'التقديم مغلق'})

    try:
        # pick 10 random questions
        q_ids = list(Question.objects.values_list('id', flat=True))
        if len(q_ids) < 10:
            return render(request, 'apply.html', {'open': False, 'closed_message': 'عدد الاسئلة أقل من 10 - تواصل مع المسؤول'})

        chosen = random.sample(q_ids, 10)
        # Generate unique session token tied to this Discord ID
        session_token = secrets.token_urlsafe(32)
        sess = TestSession.objects.create(
            application=app, 
            is_active=True, 
            questions_order=','.join(str(x) for x in chosen),
                session_token=session_token,
                discord_id=app.discord_id
        )
        app.status = 'testing'
        app.test_started_at = timezone.now()  # Mark when test started
        app.save()
        try:
            actor = get_session_user(request)
            _audit_log('start_test', actor, target=f'application:{app.id}', details=f'started test session {sess.id}')
        except Exception:
            pass
        # Store token in session for verification
        request.session[f'test_session_{sess.id}_token'] = session_token
        request.session[f'test_session_{sess.id}_discord'] = app.discord_id
        return redirect(f'/apply/test/{sess.id}/?token={session_token}')
    except Exception as exc:
        # log the exception and return a friendly page instead of 500
        logger.exception('apply_start_test: failed to start test for application %s', app_id)
        # attempt to revert any partial state
        try:
            app.status = 'open'
            app.test_started_at = None
            app.save()
        except Exception:
            logger.exception('apply_start_test: failed to revert application %s state', app_id)
        return render(request, 'apply.html', {
            'open': False,
            'closed_message': 'حدث خطأ أثناء بدء الاختبار. يرجى التواصل مع الدعم.'
        })


def apply_test_page(request, session_id):
    session = get_object_or_404(TestSession, id=session_id)
    app = session.application
    # Require the user to be logged in via Discord OAuth
    discord_in_session = request.session.get('discord_id')
    if not discord_in_session:
        request.session['error_message'] = 'يرجى تسجيل الدخول عبر Discord للوصول إلى الاختبار.'
        return redirect('apply_page')
    
    # Security: Verify token from URL to ensure it's the correct person accessing
    token_from_url = request.GET.get('token', '').strip()
    token_from_session = request.session.get(f'test_session_{session_id}_token', '')
    
    # Token must match either from URL (first access) or session (refresh)
    valid_token = (token_from_url == session.session_token) or (token_from_session == session.session_token)
    
    if not valid_token or not session.session_token:
        # Unauthorized access - redirect to apply page
        request.session['error_message'] = 'هذا الرابط مخصص لشخص آخر. يرجى بدء طلب تقديم جديد.'
        return redirect('apply_page')
    
    # Security: Verify Discord ID matches (prevent link sharing between users)
    if session.discord_id != app.discord_id:
        request.session['error_message'] = 'عذراً، لا يمكنك الدخول للاختبار. هذا الرابط مخصص لشخص آخر.'
        return redirect('apply_page')

    # Ensure current logged-in Discord account matches the test session owner
    if discord_in_session != session.discord_id:
        request.session['error_message'] = 'أنت غير مسجل دخول على الحساب الذي يجري الاختبار.'
        return redirect('apply_page')
    
    # Check if session is already being used by someone else (can only be active in one session at a time)
    session_user_id = request.session.get(f'test_session_{session_id}_user_id', None)
    current_user_id = request.session.session_key
    
    if session_user_id is not None and session_user_id != current_user_id:
        # Different user trying to access - reject
        request.session['error_message'] = 'هذا الاختبار قيد الاستخدام من قبل شخص آخر. لا يمكن الوصول إليه.'
        return redirect('apply_page')
    
    # Store user session ID for this test session (prevents sharing)
    request.session[f'test_session_{session_id}_user_id'] = current_user_id
    
    # Verify that this session was just created (within last 5 minutes) to prevent access to old sessions
    if session.finished_at is not None:
        # Test already finished, user cannot retake it
        request.session['error_message'] = 'لقد انتهيت من الاختبار بالفعل. يُسمح بمحاولة واحدة فقط.'
        return redirect('apply_page')
    
    # basic page that will load first question via JS
    qids = session.question_ids()
    if not qids:
        return render(request, 'apply_test.html', {'error': 'جلسة الاختبار غير صالحة'})

    # Compute remaining initial countdown (so refresh doesn't reset it)
    INITIAL_COUNTDOWN = 120
    remaining = INITIAL_COUNTDOWN
    try:
        if app.test_started_at:
            elapsed = (timezone.now() - app.test_started_at).total_seconds()
            remaining = int(max(0, INITIAL_COUNTDOWN - elapsed))
    except Exception:
        remaining = INITIAL_COUNTDOWN
    
    # Store token in session for future requests
    request.session[f'test_session_{session_id}_token'] = session.session_token

    # send minimal context: session id and question ids
    return render(request, 'apply_test.html', {
        'session': session,
        'question_ids': qids,
        'question_time_seconds': 60,
        'initial_countdown_seconds': remaining  # remaining seconds for initial timer
    })


@require_POST
def apply_submit_answer(request, session_id):
    session = get_object_or_404(TestSession, id=session_id)
    
    # Security: Verify token to ensure it's the correct person submitting
    token_from_post = request.POST.get('token', '').strip()
    token_from_session = request.session.get(f'test_session_{session_id}_token', '')
    
    # Token must match
    valid_token = (token_from_post == session.session_token) or (token_from_session == session.session_token)
    
    if not valid_token or not session.session_token:
        return JsonResponse({'error': 'غير مصرح لك بالإجابة. هذا الاختبار مخصص لشخص آخر.'}, status=403)

    # Require the user to be logged in via Discord OAuth
    discord_in_session = request.session.get('discord_id')
    if not discord_in_session:
        return JsonResponse({'error': 'يرجى تسجيل الدخول عبر Discord للوصول إلى الاختبار.'}, status=403)

    # Verify Discord ID matches the application and the logged-in account
    if session.discord_id != session.application.discord_id or discord_in_session != session.discord_id:
        return JsonResponse({'error': 'أنت غير مسجل دخول على الحساب الذي يجري الاختبار.'}, status=403)
    
    # Verify this is the same user (session) that started the test
    session_user_id = request.session.get(f'test_session_{session_id}_user_id', None)
    current_user_id = request.session.session_key
    
    if session_user_id != current_user_id:
        return JsonResponse({'error': 'هذا الاختبار قيد الاستخدام من قبل شخص آخر.'}, status=403)
    
    if not session.is_active:
        return JsonResponse({'error': 'الجلسة غير نشطة'}, status=403)

    qid = int(request.POST.get('question_id'))
    sel = request.POST.get('selected_index')
    try:
        sel_index = int(sel)
    except:
        sel_index = None

    q = get_object_or_404(Question, id=qid)
    is_correct = (sel_index is not None and sel_index == q.correct_index)
    ans = ApplicantAnswer.objects.create(session=session, question=q, selected_index=sel_index, is_correct=is_correct)

    # update score incrementally (score out of 10)
    total_correct = ApplicantAnswer.objects.filter(session=session, is_correct=True).count()
    session.score = (total_correct / 10.0) * 10.0
    session.save()

    # check if finished
    answered = ApplicantAnswer.objects.filter(session=session).count()
    if answered >= 10:
        session.is_active = False
        session.finished_at = timezone.now()
        session.save()
        session.application.status = 'completed'
        session.application.save()
        try:
            actor = get_session_user(request)
            _audit_log('finish_test', actor, target=f'session:{session.id}', details=f'session finished with score {session.score}')
        except Exception:
            pass

    return JsonResponse({'ok': True, 'is_correct': is_correct, 'answered': answered})


def apply_test_finished(request, app_id):
    """صفحة تظهر بعد انتهاء الاختبار - لا يمكن الرجوع للخلف"""
    app = get_object_or_404(Application, id=app_id)
    
    # التحقق من أن الاختبار انتهى بالفعل
    if app.status != 'completed':
        return redirect('apply_page')
    
    return render(request, 'apply_test_finished.html', {
        'application': app
    })


@rank_required(applications_only=True)
def admin_applications_view(request):
    # show non-hidden applications and attach latest score for quick review
    from datetime import timedelta
    q = (request.GET.get('q') or '').strip()
    qs = Application.objects.filter(is_hidden=False)
    if q:
        qs = qs.filter(models.Q(discord_id__icontains=q) | models.Q(character_name__icontains=q))
    apps = list(qs.order_by('-submitted_at').all())
    for a in apps:
        last = a.sessions.order_by('-finished_at', '-started_at').first()
        a.last_score = last.score if last else None
        
        # Check if test is still ongoing (120s initial + 600s for 10 questions = 720s total)
        # 120 seconds initial countdown + 60 seconds per question * 10 questions = 720 seconds total
        TEST_DURATION = 720  # seconds
        # Consider the application as "testing" only when its status is explicitly 'testing'
        # and the test_started_at timestamp is within the allowed duration.
        if a.status == 'testing' and a.test_started_at:
            elapsed = (timezone.now() - a.test_started_at).total_seconds()
            a.is_testing = elapsed < TEST_DURATION
        else:
            a.is_testing = False

        # Detect interrupted test sessions: a session that was active but was stopped
        # by admin (is_active False and no finished_at) — mark for UI to restrict actions.
        a.test_interrupted = False
        try:
            last_session = a.sessions.order_by('-started_at').first()
            if last_session and not last_session.is_active and last_session.finished_at is None and last_session.started_at:
                # If application status is closed or session was force-stopped, show interrupted state
                a.test_interrupted = True
        except Exception:
            a.test_interrupted = False

    setting = ApplicationSetting.objects.first()
    user = get_session_user(request)
    return render(request, 'admin_applications.html', {'applications': apps, 'setting': setting, 'q': q, 'user': user})


@rank_required(applications_only=True)
def admin_application_action(request, app_id):
    app = get_object_or_404(Application, id=app_id)
    action = request.POST.get('action')
    # actions: prelim_accept, final_accept, send_dm_custom, reject, close_with_timer, close_with_message, open, hide, unhide

    discord_user_raw = (app.discord_id or '')
    # Normalize common mention formats like <@123...> or <@!123...> to plain snowflake digits
    m = re.findall(r"\d+", discord_user_raw)
    discord_user = m[0] if m else discord_user_raw

    # logging helper: post admin actions to a configured discord channel (fallback to provided channel)
    def _log_action(msg):
        # remove timestamps like ' at 2026-01-31T...' and collapse whitespace, truncate
        try:
            clean = re.sub(r"\bat\s+\S+", '', msg)
            clean = re.sub(r'\s+', ' ', clean).strip()
            if len(clean) > 250:
                clean = clean[:247] + '...'
            ch = os.getenv('DISCORD_LOG_CHANNEL_ID', '1446744094952128733')
            discord_utils.send_channel_message(ch, clean)
        except Exception:
            pass

    user = get_session_user(request)

    if action == 'prelim_accept':
        app.status = 'completed'
        app.save()
        # رسالة القبول المبدئي
        msg = f"""⁨`السلام عليكم ورحمة الله وبركاته`⁩⁩**

تم قبولك قبول مبدئي في شرطة هيل ستيت. نرجو منك مراجعة روم <#1446744092615774272>

شاكرين لك .
(<@{discord_user}>)
**"""
        role_id = request.POST.get('role_id') or os.getenv('ROLE_PRELIMINARY_ACCEPTANCE')
        if discord_user:
            try:
                discord_utils.send_dm(discord_user, msg)
            except Exception:
                pass
        if role_id and discord_user:
            try:
                discord_utils.add_role(discord_user, role_id)
            except Exception:
                pass

        # سجّل الحدث بالعربي
        try:
            _audit_log('prelim_accept', user, target=f'application:{app.id}', details=f'المتقدم: {app.character_name} ({app.discord_id})')
        except Exception:
            pass

    elif action == 'final_accept':
        app.status = 'completed'
        app.save()
        discord_name = discord_utils.get_guild_member_username(discord_user) or f'cadet{discord_user}'
        base_username = discord_name.split('#')[0]
        # sanitize base username: allow letters, digits, dot, underscore, dash
        base_clean = re.sub(r'[^A-Za-z0-9_.-]', '', base_username)
        if not base_clean:
            base_clean = f'cadet{discord_user}'
        # limit length to 30 chars to fit username field
        base_clean = base_clean[:30]
        username = base_clean
        suffix = 1
        while User.objects.filter(username=username).exists():
            username = f"{base_clean}{suffix}"
            suffix += 1

        password = secrets.token_urlsafe(8)
        cadet = User(username=username, full_name=app.character_name, rank='cadet')
        cadet.set_password(password)
        cadet.save()

        msg = f"""**
السلام عليكم ورحمة الله وبركاته

تم قبولك قبول نهائي في شرطة هيل ستيت. نرجو منك مراجعة جميع التعاميم المنشورة.

ونرجوا منك مراجعة حسابك على الموقع الإلكتروني لإكمال جميع إجراءات تقييم الكاديت وشكراً لك.

`Username : {username}`

`Password : {password}`

(<@{discord_user}>)
**"""
        if discord_user:
            try:
                sent = discord_utils.send_dm(discord_user, msg)
                if not sent:
                    Notification.objects.create(user=cadet, message=f"تم إنشاء حسابك لكن فشل إرسال رسالة الديسكورد. بيانات الدخول:\n{msg}")
            except Exception:
                Notification.objects.create(user=cadet, message=f"تم إنشاء حسابك لكن حدث خطأ أثناء محاولة إرسال رسالة الديسكورد. بيانات الدخول:\n{msg}")
        else:
            Notification.objects.create(user=cadet, message=f"تم إنشاء حسابك. بيانات الدخول:\n{msg}")

        role_id = request.POST.get('role_id') or os.getenv('ROLE_FINAL_ACCEPTANCE')
        if role_id and discord_user:
            try:
                role_added = discord_utils.add_role(discord_user, role_id)
                if not role_added:
                    Notification.objects.create(user=cadet, message="تم إنشاء حسابك، ولكن فشل إضافة الدور في ديسكورد. تواصل مع الإدارة.")
            except Exception:
                Notification.objects.create(user=cadet, message="تم إنشاء حسابك، ولكن حدث خطأ أثناء محاولة إضافة الدور على ديسكورد.")

        # سجّل الحدث بالعربي
        try:
            _audit_log('final_accept', user, target=f'application:{app.id}', details=f'المتقدم: {app.character_name} ({app.discord_id})؛ حساب: {username}')
        except Exception:
            pass

    elif action == 'retest':
        # Retest action disabled: prevent changing status to 'testing'. Log the attempted action.
        try:
            actor = get_session_user(request)
            _audit_log('retest_disabled', actor, target=f'application:{app.id}', details='retest action was blocked by system settings')
        except Exception:
            pass

    elif action == 'send_dm_custom':
        # هذا الأكشن الجديد لإرسال رسالة خاصة بدون تغيير أي حالة
        custom_msg = request.POST.get('message', '').strip()
        if custom_msg and discord_user:
            try:
                discord_utils.send_dm(discord_user, custom_msg)
            except Exception:
                pass  # نترك الفشل يمر بدون مشاكل

    elif action == 'reject':
        app.status = 'closed'
        app.save()
        if discord_user:
            msg = (
                "⁨⁨⁨⁨`السلام عليكم ورحمة الله وبركاته`⁩⁩⁩⁩⁩**\n\n"
                "تم رفضك في شرطة هيل ستيت يمكن التقديم في المرات المقبله\n"
                "وراجع روم <#1446744096658952326> لمعرفة التقديمات القادمة\n\n"
                "شاكرين لك .\n\n"
                f"<@{discord_user}>\n**"
            )
            try:
                discord_utils.send_dm(discord_user, msg)
            except Exception:
                pass

        try:
            _audit_log('reject', user, target=f'application:{app.id}', details=f'المتقدم: {app.character_name} ({app.discord_id})')
        except Exception:
            pass

    elif action == 'close_with_message':
        msg = request.POST.get('message', '')
        app.status = 'closed'
        app.closed_message = msg
        app.reopen_at = None
        app.save()

        try:
            _audit_log('close_with_message', user, target=f'application:{app.id}', details=f'أُغلق الطلب بالرسالة: {msg[:160]}')
        except Exception:
            pass

    elif action == 'close_with_timer':
        dt = request.POST.get('reopen_at')
        reopen = _parse_reopen_dt(dt)
        if reopen:
            app.status = 'closed'
            app.reopen_at = reopen
            app.save()
            try:
                _audit_log('close_with_timer', user, target=f'application:{app.id}', details=f'أُغلق الطلب حتى: {reopen}')
            except Exception:
                pass

    elif action == 'open':
        app.status = 'open'
        app.closed_message = ''
        app.reopen_at = None
        app.save()

        try:
            _audit_log('open', user, target=f'application:{app.id}', details='تم فتح الطلب')
        except Exception:
            pass

    elif action == 'hide':
        app.is_hidden = True
        app.save()

        try:
            _audit_log('hide', user, target=f'application:{app.id}', details='تم إخفاء الطلب')
        except Exception:
            pass

    elif action == 'unhide':
        app.is_hidden = False
        app.save()

        try:
            _audit_log('unhide', user, target=f'application:{app.id}', details='تم إظهار الطلب')
        except Exception:
            pass

    return redirect('admin_applications')



@rank_required(applications_only=True)
def admin_application_detail(request, app_id):
    app = get_object_or_404(Application, id=app_id)
    last = app.sessions.order_by('-finished_at', '-started_at').first()
    if not last:
        return render(request, 'admin_application_detail.html', {'application': app, 'error': 'لا توجد جلسات لهذا المتقدم'})
    answers = ApplicantAnswer.objects.filter(session=last).select_related('question').order_by('answered_at')

    # compute simple stats here to avoid relying on non-standard template filters
    total_questions = answers.count()
    correct_count = answers.filter(is_correct=True).count()
    incorrect_count = total_questions - correct_count
    percentage = 0
    if total_questions > 0:
        try:
            percentage = int(round((correct_count / total_questions) * 100))
        except Exception:
            percentage = 0

    return render(request, 'admin_application_detail.html', {
        'application': app,
        'session': last,
        'answers': answers,
        'total_questions': total_questions,
        'correct_count': correct_count,
        'incorrect_count': incorrect_count,
        'percentage': percentage,
    })


@rank_required(dashboard_only=True)
def admin_applications_control(request):
    # Global open/close controls
    setting, _ = ApplicationSetting.objects.get_or_create(id=1)
    action = request.POST.get('action')
    if action == 'open_all':
        setting.status = 'open'
        setting.closed_message = ''
        setting.reopen_at = None
        setting.save()
        Application.objects.filter(status='closed').update(status='open')
        try:
            actor = get_session_user(request)
            _audit_log('open_all', actor, target='applications', details='opened all applications')
        except Exception:
            pass
    elif action == 'close_with_message':
        msg = request.POST.get('message', '')
        setting.status = 'closed'
        setting.closed_message = msg
        setting.reopen_at = None
        setting.save()
        # close all open applications
        Application.objects.filter(status='open').update(status='closed', closed_message=msg)
        # stop active sessions immediately and mark their applications closed as well
        active_sessions = TestSession.objects.filter(is_active=True)
        affected_app_ids = list(active_sessions.values_list('application_id', flat=True).distinct())
        active_sessions.update(is_active=False)
        if affected_app_ids:
            Application.objects.filter(id__in=affected_app_ids).update(status='closed', closed_message=msg, reopen_at=None)
        try:
            actor = get_session_user(request)
            _audit_log('close_with_message_global', actor, target='applications', details=f'closed all with message: {msg}')
        except Exception:
            pass
    elif action == 'close_with_timer':
        dt = request.POST.get('reopen_at')
        print('DEBUG admin_action reopen_at raw:', repr(dt), flush=True)
        reopen = _parse_reopen_dt(dt)
        if reopen:
            setting.status = 'closed'
            setting.reopen_at = reopen
            setting.closed_message = ''
            setting.save()
            Application.objects.filter(status='open').update(status='closed', reopen_at=reopen)
            # stop active sessions and mark their applications closed with reopen time
            active_sessions = TestSession.objects.filter(is_active=True)
            affected_app_ids = list(active_sessions.values_list('application_id', flat=True).distinct())
            active_sessions.update(is_active=False)
            if affected_app_ids:
                Application.objects.filter(id__in=affected_app_ids).update(status='closed', reopen_at=reopen)
            try:
                actor = get_session_user(request)
                _audit_log('close_with_timer_global', actor, target='applications', details=f'closed until {reopen.isoformat()}')
            except Exception:
                pass

    return redirect('admin_applications')
