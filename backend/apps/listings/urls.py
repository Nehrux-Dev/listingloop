from rest_framework.routers import DefaultRouter

from apps.listings.views import ListingPhotoViewSet, ListingViewSet

app_name = "listings"

router = DefaultRouter()
router.register("listings", ListingViewSet, basename="listing")
router.register("listing-photos", ListingPhotoViewSet, basename="listingphoto")

urlpatterns = router.urls
