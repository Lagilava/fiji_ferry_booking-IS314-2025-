from django import forms
from .models import Cargo


class CargoBookingForm(forms.ModelForm):
    class Meta:
        model = Cargo
        fields = ['cargo_type', 'weight_kg']
        widgets = {
            'cargo_type': forms.Select(choices=[
                ('', 'Select cargo type'),
                ('parcel', 'Parcel'),
                ('pallet', 'Pallet'),
                ('vehicle', 'Vehicle'),
                ('bulk', 'Bulk'),
            ]),
            'weight_kg': forms.NumberInput(attrs={'min': 0, 'step': '0.1'}),
        }