from django import forms
from .models import Booking, Cargo

class ModifyBookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = ['passenger_adults', 'passenger_children', 'passenger_infants']
        widgets = {
            'passenger_adults': forms.NumberInput(attrs={'min': 0, 'max': 20, 'required': True}),
            'passenger_children': forms.NumberInput(attrs={'min': 0, 'max': 20}),
            'passenger_infants': forms.NumberInput(attrs={'min': 0, 'max': 20}),
        }

class CargoBookingForm(forms.ModelForm):
    class Meta:
        model = Cargo
        fields = ['cargo_type', 'weight_kg', 'dimensions_cm']
        widgets = {
            'cargo_type': forms.Select(choices=[
                ('', 'Select cargo type'),
                ('parcel', 'Parcel'),
                ('pallet', 'Pallet'),
                ('vehicle', 'Vehicle'),
                ('bulk', 'Bulk'),
            ]),
            'weight_kg': forms.NumberInput(attrs={'min': 0, 'step': '0.1'}),
            'dimensions_cm': forms.TextInput(attrs={'placeholder': 'e.g., 100x50x30'}),
        }