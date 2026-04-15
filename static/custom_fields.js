function taskTypesRenderColorPopover(controller, config) {
  if (!controller.isPopoverOpen(config)) return '';
  const palette = PRESET_COLORS.map(color => `
    <button
      type="button"
      data-action="${config.onSetAction}"
      data-type-id="${config.typeId}"
      ${config.fieldId ? `data-field-id="${config.fieldId}"` : ''}
      ${config.optionIndex !== null ? `data-option-index="${config.optionIndex}"` : ''}
      data-color="${color}"
      class="w-6 h-6 rounded-full hover:scale-110 transition-transform border border-black/10 ${controller.paletteColorClass(config.currentColor, color)}"
    ></button>
  `).join('');
  return `
    <div class="absolute top-8 left-0 bg-white shadow-xl rounded-xl p-3 z-20 w-48" data-role="popover">
      <div class="flex flex-wrap gap-2">
        ${palette}
        <button
          type="button"
          data-action="${config.onClearAction}"
          data-type-id="${config.typeId}"
          ${config.fieldId ? `data-field-id="${config.fieldId}"` : ''}
          ${config.optionIndex !== null ? `data-option-index="${config.optionIndex}"` : ''}
          class="w-6 h-6 rounded-full bg-gray-100 border border-dashed border-gray-300 flex items-center justify-center text-gray-400 text-xs hover:bg-gray-200"
          title="No color"
        >✕</button>
      </div>
    </div>
  `;
}

function taskTypesRenderCustomFields(controller, tt) {
  return `
    <div class="px-5 py-3">
      <div class="flex items-center justify-between mb-2">
        <span class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Custom Fields</span>
        ${controller.canEdit ? `<button type="button" data-action="toggle-add-field" data-type-id="${tt.id}" class="text-xs text-blue-500 hover:text-blue-700 font-medium">+ Add field</button>` : ''}
      </div>
      ${controller.hasCustomFields(tt) ? `<div class="space-y-1 mb-2">${tt.custom_fields.map(field => taskTypesRenderField(controller, tt, field)).join('')}</div>` : '<p class="text-sm text-gray-400 italic py-1">No custom fields yet.</p>'}
      ${tt.showAddField && controller.canEdit ? taskTypesRenderAddFieldForm(controller, tt) : ''}
    </div>
  `;
}

function taskTypesRenderField(controller, tt, field) {
  const fieldPopover = taskTypesRenderColorPopover(controller, {
    kind: 'field-color',
    typeId: tt.id,
    fieldId: field.id,
    optionIndex: null,
    currentColor: field.color,
    onSetAction: 'set-field-color',
    onClearAction: 'clear-field-color',
  });

  const dropdownOptions = field.field_type === 'dropdown' ? taskTypesRenderFieldOptions(controller, tt, field) : '';

  return `
    <div class="bg-gray-50 rounded-lg group">
      <div class="flex items-center justify-between py-1.5 px-3">
        <div class="flex items-center gap-2.5">
          <div class="relative flex-shrink-0" data-role="color-popover-anchor">
            <button
              type="button"
              data-action="toggle-field-color"
              data-type-id="${tt.id}"
              data-field-id="${field.id}"
              class="w-4 h-4 rounded border border-black/15 hover:scale-110 transition-transform ${controller.colorSwatchClass(field.color)}"
              title="Pick color"
              ${renderDisabled(!controller.canEdit)}
            ></button>
            ${fieldPopover}
          </div>
          <span class="text-sm font-medium text-gray-700">${escapeHtml(field.name)}</span>
          <span class="text-xs bg-white border text-gray-500 px-2 py-0.5 rounded">${escapeHtml(field.field_type)}</span>
        </div>
        <div class="flex items-center gap-3">
          <label class="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none" title="${escapeHtml(controller.fieldShowOnCardTitle(field))}">
            <input type="checkbox" data-field="field-show-on-card" data-type-id="${tt.id}" data-field-id="${field.id}" class="h-3.5 w-3.5 rounded accent-blue-500"${renderChecked(field.show_on_card)}${renderDisabled(!controller.canEdit)}>
            Show on card
          </label>
          ${controller.canEdit ? `<button type="button" data-action="delete-field" data-type-id="${tt.id}" data-field-id="${field.id}" class="text-gray-300 hover:text-red-500 transition-colors opacity-0 group-hover:opacity-100">×</button>` : ''}
        </div>
      </div>
      ${dropdownOptions}
    </div>
  `;
}

function taskTypesRenderFieldOptions(controller, tt, field) {
  const optionChips = (field.options || []).map((opt, index) => {
    const optionPopover = taskTypesRenderColorPopover(controller, {
      kind: 'field-option-color',
      typeId: tt.id,
      fieldId: field.id,
      optionIndex: index,
      currentColor: opt.color,
      onSetAction: 'set-field-option-color',
      onClearAction: 'clear-field-option-color',
    });
    return `
      <span class="relative flex items-center gap-1 text-xs bg-white border rounded-md px-1.5 py-0.5 text-gray-700" data-role="color-popover-anchor">
        <button
          type="button"
          data-action="toggle-field-option-color"
          data-type-id="${tt.id}"
          data-field-id="${field.id}"
          data-option-index="${index}"
          class="w-3.5 h-3.5 rounded border border-black/15 hover:scale-110 transition-transform ${controller.colorSwatchClass(opt.color)}"
          title="Pick option color"
          ${renderDisabled(!controller.canEdit)}
        ></button>
        <span>${escapeHtml(opt.label)}</span>
        ${controller.canEdit ? `<button type="button" data-action="remove-field-option" data-type-id="${tt.id}" data-field-id="${field.id}" data-option-index="${index}" class="text-gray-300 hover:text-red-400 ml-0.5 leading-none">×</button>` : ''}
        ${optionPopover}
      </span>
    `;
  }).join('');

  return `
    <div class="px-3 pb-2.5 border-t border-gray-200">
      <div class="flex flex-wrap gap-1 mt-2 mb-1.5">
        ${optionChips || '<span class="text-xs text-gray-400 italic py-0.5">No options yet</span>'}
      </div>
      ${controller.canEdit ? `
        <div class="flex gap-1.5">
          <input
            type="text"
            data-field="field-new-option"
            data-type-id="${tt.id}"
            data-field-id="${field.id}"
            value="${escapeHtml(field.newOption || '')}"
            placeholder="New option..."
            class="flex-1 border rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
          >
          <button type="button" data-action="add-field-option" data-type-id="${tt.id}" data-field-id="${field.id}" class="text-xs bg-white border hover:bg-gray-100 px-2 py-1 rounded-lg transition-colors">Add</button>
        </div>
      ` : ''}
    </div>
  `;
}

function taskTypesRenderAddFieldForm(controller, tt) {
  const optionChips = tt.newField.options.map((opt, index) => {
    const optionPopover = taskTypesRenderColorPopover(controller, {
      kind: 'new-field-option-color',
      typeId: tt.id,
      fieldId: null,
      optionIndex: index,
      currentColor: opt.color,
      onSetAction: 'set-new-field-option-color',
      onClearAction: 'clear-new-field-option-color',
    });
    return `
      <span class="relative flex items-center gap-1 text-xs bg-white border rounded-md px-1.5 py-0.5 text-gray-700" data-role="color-popover-anchor">
        <button
          type="button"
          data-action="toggle-new-field-option-color"
          data-type-id="${tt.id}"
          data-option-index="${index}"
          class="w-3.5 h-3.5 rounded border border-black/15 hover:scale-110 transition-transform ${controller.colorSwatchClass(opt.color)}"
          title="Pick option color"
          ${renderDisabled(!controller.canEdit)}
        ></button>
        <span>${escapeHtml(opt.label)}</span>
        <button type="button" data-action="remove-new-field-option" data-type-id="${tt.id}" data-option-index="${index}" class="text-gray-300 hover:text-red-400 ml-0.5 leading-none">×</button>
        ${optionPopover}
      </span>
    `;
  }).join('');

  return `
    <div class="mt-2 bg-blue-50 rounded-lg p-3">
      <div class="flex gap-2 items-end flex-wrap">
        <div class="flex-1 min-w-32">
          <label class="block text-xs text-gray-500 mb-1">Field name</label>
          <input
            type="text"
            data-field="new-field-name"
            data-type-id="${tt.id}"
            value="${escapeHtml(tt.newField.name)}"
            placeholder="e.g. Assignee, Status..."
            class="w-full border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
          >
        </div>
        <div>
          <label class="block text-xs text-gray-500 mb-1">Type</label>
          <select data-field="new-field-type" data-type-id="${tt.id}" class="border rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400">
            <option value="text"${renderSelected(tt.newField.field_type, 'text')}>Text</option>
            <option value="number"${renderSelected(tt.newField.field_type, 'number')}>Number</option>
            <option value="date"${renderSelected(tt.newField.field_type, 'date')}>Date</option>
            <option value="dropdown"${renderSelected(tt.newField.field_type, 'dropdown')}>Dropdown</option>
          </select>
        </div>
        <div class="pb-2">
          <label class="flex items-center gap-1.5 text-xs text-gray-500 cursor-pointer select-none whitespace-nowrap">
            <input type="checkbox" data-field="new-field-show-on-card" data-type-id="${tt.id}" class="h-3.5 w-3.5 rounded accent-blue-500"${renderChecked(tt.newField.show_on_card)}>
            Show on card
          </label>
        </div>
        <button type="button" data-action="add-field" data-type-id="${tt.id}" class="bg-blue-500 hover:bg-blue-600 text-white px-3 py-1.5 rounded-lg text-sm font-medium transition-colors">Add</button>
        <button type="button" data-action="cancel-add-field" data-type-id="${tt.id}" class="text-gray-500 hover:text-gray-700 px-2 py-1.5 text-sm">Cancel</button>
      </div>
      ${tt.newField.field_type === 'dropdown' ? `
        <div class="mt-2 pt-2 border-t border-blue-100">
          <div class="flex flex-wrap gap-1 mb-1.5">
            ${optionChips || '<span class="text-xs text-gray-400 italic py-0.5">Add at least one option</span>'}
          </div>
          <div class="flex gap-1.5">
            <input
              type="text"
              data-field="new-field-option-input"
              data-type-id="${tt.id}"
              value="${escapeHtml(tt.newField.newOption)}"
              placeholder="Option label..."
              class="flex-1 border rounded-lg px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-blue-400"
            >
            <button type="button" data-action="add-new-field-option" data-type-id="${tt.id}" class="text-xs bg-white border hover:bg-gray-100 px-2 py-1 rounded-lg transition-colors">Add option</button>
          </div>
        </div>
      ` : ''}
    </div>
  `;
}
