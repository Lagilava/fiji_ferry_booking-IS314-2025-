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
          $el.select2({
            width: '100%',
            minimumInputLength: getMinimumInputLength($el)
          });
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
              return $('<span>').attr('style', $option.attr('style')).text(data.text);
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
    if (!window.WEBSOCKET_CONFIG) {
      console.warn('⚠️ WEBSOCKET_CONFIG not found, skipping WebSocket initialization');
      return;
    }

    if (window.adminWS && !window.adminWS.disabled) {
      console.log('✅ Using existing adminWS for change list WebSocket');
      window.adminWS.on('message', handleWebSocketMessage);
    } else {
      console.log('✅ Initializing new WebSocket for change list');
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
          handleWebSocketMessage(data);
        } catch (err) {
          console.error('Error parsing WebSocket message:', err);
        }
      };
    }
  }

  function handleWebSocketMessage(data) {
    if (data.type && data.type.endsWith('_update') && window.__IS_CHANGE_LIST__) {
      const model = data.model || data.type.replace('_update', '');
      const context = window.CHANGE_LIST_CONTEXT || {};
      if (model === context.model_name) {
        const id = data.instance_id || data[`${model}_id`] || data.id;
        if (id) {
          console.log(`${model} updated via WebSocket:`, data);
          updateRow(model, id, data);
        } else {
          console.warn('No ID found in WebSocket data for update');
        }
      }
    } else {
      console.warn('Unknown or unhandled WebSocket message type:', data.type);
    }
  }

  function getFetchUrl(model, id) {
    const context = window.CHANGE_LIST_CONTEXT || {};
    const app_label = context.app_label || 'bookings';
    return `/admin/${app_label}/${model}/${id}/json/`;
  }

  function updateRow(model, id, wsData) {
    const $table = $('table#result_list');
    const $tableBody = $table.find('tbody');

    if (!$table.length || $tableBody.length === 0) {
      console.error('⚠️ Table #result_list or tbody not found in DOM');
      return;
    }

    const isDataTable = $.fn.DataTable && $.fn.DataTable.isDataTable('#result_list');
    const rowCount = $tableBody.find('tr').length;
    const visibleRowIds = $tableBody.find('tr').map(function() {
      return $(this).data('id');
    }).get().join(', ');

    console.log(`Table #result_list status: isDataTable=${isDataTable}, rowCount=${rowCount}, visibleRowIds=${visibleRowIds || 'none'}`);

    const $row = $tableBody.find(`tr[data-id="${id}"]`);

    if ($row.length) {
      // --- Update existing row dynamically ---
      if (wsData.action === 'delete') {
        $row.remove();
        console.log(`✅ Removed row ${id} for model ${model}`);
      } else {
        fetchJsonAndUpdate(model, id, $row, wsData);
      }
    } else {
      fetchJsonAndCheck(model, id, wsData);
    }
  }

  function fetchJsonAndUpdate(model, id, $row, wsData) {
    let fetchUrl = getFetchUrl(model, id);
    const searchParams = new URLSearchParams(window.location.search).toString();
    if (searchParams) {
      fetchUrl += `?${searchParams}`;
    }

    fetch(fetchUrl, {
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': getCookie('csrftoken')
      }
    })
    .then(response => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return response.json();
    })
    .then(data => {
      if (data.exists) {
        Object.keys(data.data || {}).forEach(field => {
          const $cell = $row.find(`td[data-field="${field}"]`);
          if ($cell.length) {
            $cell.html(data.data[field] ?? 'N/A');
          } else {
            console.warn(`⚠️ No cell found for field "${field}" in ${model} ${id}`);
          }
        });

        $row.addClass('table-warning');
        setTimeout(() => $row.removeClass('table-warning'), 2000);
        console.log(`✅ Updated row ${id} for model ${model}`);
      } else {
        console.warn(`Object ${id} for model ${model} no longer exists`);
      }
    })
    .catch(error => {
      console.error(`Error fetching ${model} ${id}:`, error);
    });
  }

  function fetchJsonAndCheck(model, id, wsData) {
    const context = window.CHANGE_LIST_CONTEXT || {};
    const currentPage = context.page_num || 'unknown';
    const filters = context.has_filters ? context.current_url : 'none';
    console.warn(`⚠️ No row found for ${model} ${id}, skipping update. Current page: ${currentPage}, Filters: ${filters}`);

    let fetchUrl = getFetchUrl(model, id);
    const searchParams = new URLSearchParams(window.location.search).toString();
    if (searchParams) {
      fetchUrl += `?${searchParams}`;
    }

    fetch(fetchUrl, {
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': getCookie('csrftoken')
      }
    })
    .then(response => {
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      return response.json();
    })
    .then(data => {
      if (data.exists && data.matches_filters) {
        console.log(`${model} ${id} matches current filters, reloading page`);
        window.location.reload();
      } else {
        // Show UI notification
        const $notification = $('<div class="alert alert-info alert-dismissible fade show" role="alert">' +
          `${model.charAt(0).toUpperCase() + model.slice(1)} ${id} updated but not visible on this page (Page ${currentPage}). ` +
          '<button type="button" class="close" data-dismiss="alert" aria-label="Close"><span aria-hidden="true">&times;</span></button>' +
          '</div>');
        $('#content-main').prepend($notification);
        setTimeout(() => $notification.alert('close'), 5000);
      }
    })
    .catch(error => {
      console.error(`Error fetching ${model} ${id}:`, error);
      // Fallback: Show UI notification
      const $notification = $('<div class="alert alert-info alert-dismissible fade show" role="alert">' +
        `${model.charAt(0).toUpperCase() + model.slice(1)} ${id} updated but not visible on this page (Page ${currentPage}). ` +
        '<button type="button" class="close" data-dismiss="alert" aria-label="Close"><span aria-hidden="true">&times;</span></button>' +
        '</div>');
      $('#content-main').prepend($notification);
      setTimeout(() => $notification.alert('close'), 5000);
    });
  }

  // Helper to get CSRF token
  function getCookie(name) {
    let cookieValue = null;
    if (document.cookie && document.cookie !== '') {
      const cookies = document.cookie.split(';');
      for (let i = 0; i < cookies.length; i++) {
        const cookie = cookies[i].trim();
        if (cookie.substring(0, name.length + 1) === (name + '=')) {
          cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
          break;
        }
      }
    }
    return cookieValue;
  }

  // --- Document Ready ---
  $(document).ready(function () {
    $('.actions select').addClass('form-control').select2({ width: 'element' });
    initSearchFilters();
    initRawIdFields();
    initChangeListWebSocket();
  });

})(jQuery);