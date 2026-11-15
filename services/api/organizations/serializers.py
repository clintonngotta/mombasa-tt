from rest_framework import serializers

from .models import JoinRequest, Membership, Organization


class OrganizationSerializer(serializers.ModelSerializer):
    name = serializers.CharField(max_length=120, trim_whitespace=True)
    town = serializers.CharField(max_length=80, trim_whitespace=True)

    class Meta:
        model = Organization
        fields = ["id", "name", "town", "kind"]


class MembershipSerializer(serializers.ModelSerializer):
    organization = OrganizationSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "organization", "role", "status", "joined_at"]
        read_only_fields = fields


class JoinRequestSerializer(serializers.ModelSerializer):
    """Staff view of a request. Shows the requester's display name only, never their email."""

    display_name = serializers.CharField(source="user.display_name", read_only=True)

    class Meta:
        model = JoinRequest
        fields = ["id", "user", "display_name", "status", "created_at", "decided_at"]
        read_only_fields = fields


class MyJoinRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = JoinRequest
        fields = ["id", "organization", "status", "created_at", "decided_at"]
        read_only_fields = fields
