from rest_framework import serializers
from .models import DynamicForm, FormSubmission, CatalogItem
from .services import validate_form_schema, normalize_schema
from .forms import FormAccessSettingsForm


class DynamicFormSerializer(serializers.ModelSerializer):
    public_url = serializers.SerializerMethodField()
    submission_count = serializers.IntegerField(source="submissions.count", read_only=True)
    access_emails = serializers.ListField(child=serializers.EmailField(), write_only=True, required=False, max_length=100)
    access_groups = serializers.ListField(child=serializers.SlugField(max_length=100), write_only=True, required=False, max_length=100)
    allowed_people = serializers.SerializerMethodField()

    class Meta:
        model = DynamicForm
        fields = ("id", "title", "slug", "description", "purpose", "schema", "status", "visibility", "access_emails", "access_groups", "allowed_people", "public_url", "submission_count", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at", "public_url", "submission_count")
        extra_kwargs = {"slug": {"required": False, "allow_blank": True}}

    def get_public_url(self, form):
        request = self.context.get("request")
        path = f"/org/{form.organization.slug}/{form.slug}/"
        return request.build_absolute_uri(path) if request else path

    def get_allowed_people(self, form):
        request = self.context.get("request")
        if request and form.organization.memberships.filter(user=request.user, role__in=("admin", "manager")).exists():
            return list(form.allowed_users.values_list("email", flat=True))
        return []

    def validate_slug(self, value):
        if value in {"settings", "people", "menu", "submissions", "forms"}:
            raise serializers.ValidationError("This link name is reserved for workspace pages.")
        return value

    def validate(self, attrs):
        organization = self.instance.organization if self.instance else self.context.get("organization")
        if organization and attrs.get("slug"):
            others = organization.forms.filter(slug=attrs["slug"])
            if self.instance:
                others = others.exclude(pk=self.instance.pk)
            if others.exists():
                raise serializers.ValidationError({"slug": "This form link is already in use."})
        if self.instance is None or "visibility" in attrs or "access_emails" in attrs or "access_groups" in attrs:
            emails = attrs.pop("access_emails", None)
            if emails is None:
                emails = list(self.instance.allowed_users.values_list("email", flat=True)) if self.instance else []
            access = FormAccessSettingsForm({
                "visibility": attrs.get("visibility", self.instance.visibility if self.instance else DynamicForm.VISIBILITY_ORGANIZATION),
                "access_emails": "\n".join(emails),
            })
            if not access.is_valid():
                raise serializers.ValidationError(dict(access.errors))
            attrs["allowed_users"] = access.allowed_accounts
            aliases = attrs.pop("access_groups", None)
            if aliases is None:
                aliases = list(self.instance.allowed_groups.values_list("alias", flat=True)) if self.instance else []
            if organization:
                groups = list(organization.groups.filter(alias__in=aliases))
                if len(groups) != len(set(aliases)):
                    raise serializers.ValidationError({"access_groups": "Choose groups from this organization."})
                attrs["allowed_groups"] = groups
        return attrs

    def validate_schema(self, value):
        try:
            organization = self.instance.organization if self.instance else self.context.get("organization")
            return normalize_schema(value, organization) if organization else validate_form_schema(value)
        except Exception as exc:
            raise serializers.ValidationError(str(exc)) from exc


class FormSubmissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = FormSubmission
        fields = ("id", "form", "data", "respondent_name", "respondent_email", "created_at")
        read_only_fields = ("id", "form", "created_at")


class CatalogItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = CatalogItem
        fields = (
            "id",
            "name",
            "category",
            "description",
            "barcode",
            "price",
            "is_available",
        )


class CatalogItemCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CatalogItem
        fields = (
            "name",
            "category",
            "description",
            "barcode",
            "price",
            "is_available",
        )

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Price must be zero or greater.")
        return value
