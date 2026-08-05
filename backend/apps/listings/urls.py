from django.urls import path
from rest_framework.routers import DefaultRouter

from apps.listings.public_views import public_listing, submit_enquiry
from apps.listings.views import EnquiryViewSet, ListingPhotoViewSet, ListingViewSet

app_name = "listings"

router = DefaultRouter()
router.register("listings", ListingViewSet, basename="listing")
router.register("listing-photos", ListingPhotoViewSet, basename="listingphoto")
router.register("enquiries", EnquiryViewSet, basename="enquiry")

urlpatterns = router.urls + [
    # The only unauthenticated endpoints in the project. Kept under an
    # explicit `public/` prefix so it is obvious in the URLconf which routes
    # serve anonymous requests.
    path("public/listings/<slug:slug>/", public_listing, name="public-listing"),
    path(
        "public/listings/<slug:slug>/enquire/",
        submit_enquiry,
        name="public-enquiry",
    ),
]
