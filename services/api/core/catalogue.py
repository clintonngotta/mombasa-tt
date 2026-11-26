from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Country, Region


class CountryOptionSerializer(serializers.Serializer):
    value = serializers.CharField(source="code")
    label = serializers.CharField(source="name")


class RegionSerializer(serializers.ModelSerializer):
    cities = serializers.SlugRelatedField(many=True, read_only=True, slug_field="name")

    class Meta:
        model = Region
        fields = ["name", "cities"]


class CountryCatalogueSerializer(serializers.ModelSerializer):
    regions = RegionSerializer(many=True, read_only=True)

    class Meta:
        model = Country
        fields = ["catalogue_only", "regions"]


class CountryOptionsView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    public_actions = ("get",)  # held to the visitors' allowance (core/throttling.py)

    @extend_schema(responses={200: CountryOptionSerializer(many=True)})
    def get(self, request):
        return Response(CountryOptionSerializer(Country.objects.all(), many=True).data)


class CountryCatalogueView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    public_actions = ("get",)  # held to the visitors' allowance (core/throttling.py)

    @extend_schema(responses={200: CountryCatalogueSerializer})
    def get(self, request, code):
        country = get_object_or_404(Country.objects.prefetch_related("regions__cities"), code=code.upper())
        return Response(CountryCatalogueSerializer(country).data)
