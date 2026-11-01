from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def t(context, english, bulgarian):
    return bulgarian if context.get("language") == "bg" else english
