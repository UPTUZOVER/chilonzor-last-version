from django.contrib.auth.views import LogoutView
from django.urls import path

from .chat import (
    message_attachment_view,
    message_delete_view,
    message_inbox_view,
    message_poll_view,
    message_react_view,
    message_send_view,
)
from .views import (
    group_create_view,
    group_delete_view,
    group_list_view,
    group_update_view,
    home_view,
    SecureLoginView,
    set_language_view,
    user_create_view,
    user_delete_view,
    user_list_view,
    user_update_view,
)

app_name = "app"

urlpatterns = [
    path("language/", set_language_view, name="set_language"),
    path(
        "login/",
        SecureLoginView.as_view(),
        name="login",
    ),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("messages/", message_inbox_view, name="message_inbox"),
    path("messages/<int:pk>/", message_inbox_view, name="message_thread"),
    path("messages/system/", message_inbox_view, {"channel": "system"}, name="message_system"),
    path("messages/news/", message_inbox_view, {"channel": "news"}, name="message_news"),
    path("messages/send/", message_send_view, name="message_send"),
    path("messages/poll/", message_poll_view, name="message_poll"),
    path("messages/item/<int:message_id>/react/", message_react_view, name="message_react"),
    path("messages/item/<int:message_id>/delete/", message_delete_view, name="message_delete"),
    path("messages/item/<int:message_id>/file/", message_attachment_view, name="message_attachment"),
    path("", home_view, name="home"),
    path("users/", user_list_view, name="user_list"),
    path("users/create/", user_create_view, name="user_create"),
    path("users/<int:pk>/edit/", user_update_view, name="user_update"),
    path("users/<int:pk>/delete/", user_delete_view, name="user_delete"),
    path("groups/", group_list_view, name="group_list"),
    path("groups/create/", group_create_view, name="group_create"),
    path("groups/<int:pk>/edit/", group_update_view, name="group_update"),
    path("groups/<int:pk>/delete/", group_delete_view, name="group_delete"),
]
