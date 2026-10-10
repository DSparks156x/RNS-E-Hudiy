const hudiyKeys = {
  KEY_V: 'Previous media', KEY_N: 'Next media', KEY_UP: 'Move focus up',
  KEY_DOWN: 'Move focus down', KEY_LEFT: 'Move left', KEY_RIGHT: 'Move right',
  KEY_ENTER: 'Select / confirm', KEY_ESC: 'Go back', KEY_H: 'Hudiy home',
  KEY_M: 'Projection voice assistant', KEY_1: 'Scroll left', KEY_2: 'Scroll right',
  KEY_F: 'Navigation shortcut', KEY_G: 'Phone shortcut', KEY_J: 'Current media player',
};
const hudiyActions = { applications_menu: 'App menu', hudiy_diagnostics: 'DataView', hudiy_manager: 'RNS-E Manager' };
const commands = { 'python3 ~/rns-e_can/save_logs.py': 'Save support logs', 'sudo shutdown -h now': 'Shut down the Pi', 'sudo reboot': 'Reboot the Pi' };
function describe(binding) {
  if (!binding) return 'No Pi action';
  if (typeof binding === 'object') return hudiyActions[binding.action] || binding.action || 'No Pi action';
  return hudiyKeys[binding] || commands[binding] || (binding.startsWith('KEY_') ? `Sends ${binding}` : `Runs ${binding}`);
}
const token = binding => typeof binding === 'object' ? binding?.action : binding?.startsWith('KEY_') ? binding : null;

export function createFaceplateControls(mmi) {
  const mapped = (pattern, title, extra = {}) => {
    const short = mmi.short_press?.[pattern];
    const long = mmi.long_press?.[pattern];
    const extended = mmi.extended_press?.[pattern];
    return { title, pattern, actions: [
      ['Press', describe(short), token(short)],
      ['Hold', long ? describe(long) : short ? 'Uses the press action on release' : 'No Pi action', token(long)],
      ['Extended hold', extended ? describe(extended) : 'No additional action', token(extended)],
    ], ...extra };
  };
  const stock = title => ({ title, actions: [['RNS-E', 'Factory function; no Pi key mapping in this config.']], stock: true });
  const tv = (pattern, title) => mapped(pattern, title, { note: 'Available in TV mode with my firmware. Navigation, phone and media use Hudiy shortcuts; the projected screen depends on your Android Auto or CarPlay setup.' });
  return {
    previous: mapped('1,0', 'Previous-track button'),
    next: mapped('2,0', 'Next-track button'),
    upperLeft: mapped('64,0', 'Upper-left control button'),
    lowerLeft: mapped('128,0', 'Lower-left control button'),
    upperRight: stock('Upper-right control button'),
    lowerRight: stock('Lower-right control button'),
    knob: { ...mapped('0,16', 'Navigation knob'), actions: [
      ['Turn left', describe(mmi.short_press?.['0,64']), token(mmi.short_press?.['0,64'])],
      ['Turn right', describe(mmi.short_press?.['0,32']), token(mmi.short_press?.['0,32'])],
      ...mapped('0,16', 'Navigation knob').actions,
    ] },
    return: mapped('0,2', 'RETURN', { note: 'The longer hold sends KEY_0. Hudiy does not document a standard action for that key.' }),
    setup: mapped('0,1', 'SETUP'),
    volume: { title: 'Power / volume knob', actions: [['RNS-E', 'Adjusts the head unit’s volume and power. No Pi key mapping in this config.']], stock: true },
    radio: { ...stock('RADIO'), actions: [['RNS-E', 'Leaves TV and returns to factory radio. No Pi shortcut frame.']] },
    media: tv('0,4', 'MEDIA'), name: tv('4,0', 'NAME'), tel: tv('0,8', 'TEL'),
    nav: tv('8,0', 'NAV'), info: tv('0,12', 'INFO'), car: tv('12,0', 'CAR'),
  };
}
