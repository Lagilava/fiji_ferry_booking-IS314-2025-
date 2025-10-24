(function() {
    document.addEventListener('DOMContentLoaded', function() {
        if (window.adminWS) {
            window.adminWS.on('message', function(data) {
                if (data.type === 'model_update' && data.model === window.WEBSOCKET_CONFIG.model && data.objects[0].id == window.WEBSOCKET_CONFIG.object_id) {
                    // Update form fields
                    Object.entries(data.objects[0].fields).forEach(([key, value]) => {
                        const input = document.getElementById(`id_${key}`);
                        if (input) input.value = value;
                    });
                    document.getElementById('realtime-alert').style.display = 'block';
                    setTimeout(() => document.getElementById('realtime-alert').style.display = 'none', 3000);
                }
            });
        }
    });
})();