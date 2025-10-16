(function($) {
    'use strict';
console.log('✅ Custom change_list.js loaded');

    // --- Helper Functions ---
    $.fn.searchFilters = function () {
        this.each(function () {
            const $field = $(this);
            $field.change(function () {
                const $selected = $field.find('option:selected');
                const name = $selected.data('name');
                if (name) {
                    $field.attr('name', name);
                } else {
                    $field.removeAttr('name');
                }
            });
            $field.trigger('change');
        });
        return this;
    };

    function getMinimumInputLength($element) {
        const name = $element.data('name');
        return (name && window.filterInputLength?.[name]) ?? window.filterInputLengthDefault ?? 0;
    }

    function initSearchFilters() {
        const $filters = $('.search-filter');
        if ($filters.length) {
            $filters.searchFilters();
            $filters.each(function () {
                const $el = $(this);
                if ($el.data('name')) {
                    $el.select2({ width: '100%', minimumInputLength: getMinimumInputLength($el) });
                }
            });
        }

        const $mptt = $('.search-filter-mptt');
        if ($mptt.length) {
            $mptt.searchFilters();
            $mptt.each(function () {
                const $el = $(this);
                if ($el.data('name')) {
                    $el.select2({
                        width: '100%',
                        minimumInputLength: getMinimumInputLength($el),
                        templateResult: function (data) {
                            if (!data.element) return data.text;
                            const $option = $(data.element);
                            return $('<span></span>').attr('style', $option.attr('style')).text(data.text);
                        }
                    });
                }
            });
        }
    }

    function initRawIdFields() {
        $('.related-lookup').each(function () {
            if (!$(this).find('.fa-search').length) {
                $(this).append('<i class="fa fa-search"></i>');
            }
        });
    }

    // --- WebSocket Real-Time Updates ---
    function initChangeListWebSocket() {
        if (!window.WEBSOCKET_CONFIG) return;

        const wsUrl = window.WEBSOCKET_CONFIG.url;
        let ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('✅ WebSocket connected');
            document.dispatchEvent(new Event('admin-ws-connected'));
        };

        ws.onclose = () => {
            console.warn('⚠️ WebSocket disconnected, retrying in 5s...');
            document.dispatchEvent(new Event('admin-ws-disconnected'));
            setTimeout(initChangeListWebSocket, 5000);
        };

        ws.onerror = (e) => {
            console.error('WebSocket error:', e);
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);

                if (data.type === 'schedule_update') {
                    console.log('Schedule updated via WebSocket:', data);
                    updateScheduleRow(data);
                } else {
                    console.warn('Unknown WebSocket message type:', data.type);
                }
            } catch (err) {
                console.error('Error parsing WebSocket message:', err);
            }
        };
    }

    function updateScheduleRow(schedule) {
        const $row = $(`tr[data-object-pk="${schedule.schedule_id}"]`);
        if ($row.length) {
            // Update fields in the row dynamically
            $row.find('td[data-field="status"]').text(schedule.status || 'N/A');
            $row.find('td[data-field="available_seats"]').text(schedule.available_seats ?? 'N/A');
            // Optionally, highlight updated row
            $row.addClass('table-warning');
            setTimeout(() => $row.removeClass('table-warning'), 2000);
        } else {
            console.log(`Row for schedule ${schedule.schedule_id} not found. Consider refreshing.`);
        }
    }

    // --- Document Ready ---
    $(document).ready(function () {
        $('.actions select').addClass('form-control').select2({ width: 'element' });
        initSearchFilters();
        initRawIdFields();
        initChangeListWebSocket();
    });

})(jQuery);
