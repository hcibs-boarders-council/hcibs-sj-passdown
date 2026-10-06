from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import ItemForm
from .models import Item

def home(request):

    query = request.GET.get('q', '').strip()

    items = (
        Item.objects
        .filter(status=Item.Status.AVAILABLE)
        .select_related('owner')
        .order_by('-created_at')
    )

    if query:
        items = items.filter(title__icontains=query) | items.filter(description__icontains=query)

    return render(request, 'accounts/home.html', {'items': items, 'query': query})

@login_required(login_url='login')
@require_http_methods(['GET', 'POST'])
def create_item(request):
    if request.method == 'POST':
        form = ItemForm(request.POST)
        if form.is_valid():
            item = form.save(commit=False)
            item.owner = request.user
            item.save()
            return redirect('home')
    else:
        form = ItemForm()

    return render(request, 'accounts/item_form.html', {'form': form})