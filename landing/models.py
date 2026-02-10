from django.db import models
from django.utils import timezone
from django.utils.text import slugify

class LandingSettings(models.Model):
    # About
    about_title = models.CharField(max_length=200, blank=True)
    about_text = models.TextField(blank=True)

    # Contact
    phone = models.CharField(max_length=50, blank=True)
    telegram = models.URLField(max_length=200, blank=True)  # username yoki link
    instagram = models.URLField(max_length=200, blank=True)  # link
    address = models.CharField(max_length=255, blank=True)

    # Hero / CTA
    hero_title = models.CharField(max_length=200, blank=True)
    hero_subtitle = models.TextField(blank=True)
    cta_text = models.CharField(max_length=100, blank=True, default="POS'ga kirish")
    cta_url = models.CharField(max_length=255, blank=True, default="https://pos.uzbekburger.uz")

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "Landing Settings"

    class Meta:
        verbose_name = "Landing Settings"
        verbose_name_plural = "Landing Settings"


class Post(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=300, unique=True, blank=True)
    excerpt = models.TextField(blank=True)
    content = models.TextField()
    cover = models.ImageField(upload_to="posts/", blank=True, null=True)

    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:250] or "post"
            slug = base
            i = 2
            while Post.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base}-{i}"
                i += 1
            self.slug = slug
        if self.is_published and not self.published_at:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
