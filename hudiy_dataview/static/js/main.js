document.addEventListener('DOMContentLoaded', () => {
    const socket = io();

    // --- Configuration: Define Groups per Tab ---
    // User can edit these IDs.
    const TAB_CONFIG = {
        'engine': [
            { module: 0x01, group: 2 },   // Injection Time
            { module: 0x01, group: 3 },   // RPM, MAF, Ign Angle
            { module: 0x01, group: 20 },  // Knock Retard
            { module: 0x01, group: 106 }, // Fuel Rail
            { module: 0x01, group: 115 }, // Boost
            { module: 0x01, group: 134 }  // Temps
        ],
        'transmission': [
            { module: 0x02, group: 11 }, // Clutch 1
            { module: 0x02, group: 12 }, // Clutch 2
            { module: 0x02, group: 16 }, // Selector
            { module: 0x02, group: 19 }  // Temps
        ],
        'awd': [
            { module: 0x22, group: 1 },  // Status, Temps
            { module: 0x22, group: 3 },  // Pressure, Torque
            { module: 0x22, group: 5 }   // Modes
        ]
    };

    let currentTab = 'engine'; // Default

    // --- Tabs Logic ---
    const tabs = document.querySelectorAll('.tab-btn');
    const contents = document.querySelectorAll('.tab-content');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const newTabId = tab.dataset.tab;
            if (newTabId === currentTab) return;

            // 1. Desubscribe previous tab
            manageSubscription(currentTab, 'remove');

            // 2. Update UI
            tabs.forEach(t => t.classList.remove('active'));
            contents.forEach(c => c.classList.remove('active'));

            tab.classList.add('active');
            const target = document.getElementById(newTabId);
            if (target) target.classList.add('active');

            // 3. Subscribe new tab
            currentTab = newTabId;
            manageSubscription(currentTab, 'add');
        });
    });

    // --- SocketIO Handling ---
    socket.on('connect', () => {
        console.log('Connected to Backend');
        // Initial Subscription for default tab
        manageSubscription(currentTab, 'add');
    });

    socket.on('diagnostic_update', (msg) => {
        // msg: {module, group, data: [{value, unit}, ...]}
        const mod = msg.module; // Can be int or string depending on emit
        const grp = msg.group;
        const data = msg.data;

        // --- Engine (0x01 / 1) ---
        if (mod == 1 || mod == '0x01') {
            if (grp == 3) updateEngine003(data);
            if (grp == 20) updateEngine020(data);
            if (grp == 106) updateEngine106(data);
            if (grp == 115) updateEngine115(data);
            if (grp == 134) updateEngine134(data);
        }

        // --- Transmission (0x02 / 2) ---
        if (mod == 2 || mod == '0x02') {
            if (grp == 11) updateTransClutch1(data);
            if (grp == 12) updateTransClutch2(data);
            if (grp == 16) updateTransSelector(data);
            if (grp == 19) updateTransTemp(data);
        }

        // --- AWD (0x22 / 34) ---
        if (mod == 34 || mod == '0x22') {
            if (grp == 1) updateAWDStatus(data);
            if (grp == 3) updateAWDPerf(data);
            if (grp == 5) updateAWDModes(data);
        }
    });

    // --- Subscription Helper ---
    function manageSubscription(tabId, action) {
        const groups = TAB_CONFIG[tabId];
        if (!groups) return;

        groups.forEach(item => {
            console.log(`${action.toUpperCase()} Group: Mod ${item.module} Grp ${item.group}`);
            socket.emit('toggle_group', {
                module: item.module,
                group: item.group,
                action: action // 'add' or 'remove'
            });
        });
    }

    // --- Engine Update Functions ---

    function updateEngine002(data) {
        // Group 2: RPM, Load, Inj Time, MAF
        setText('eng_002_2', data[2]); // Injection Time
    }

    function updateEngine003(data) {
        // Group 3: RPM, MAF, Throttle, Ign Angle
        setText('eng_003_0', data[0]); // RPM
        setText('eng_003_3', data[3]); // Ignition

        // MAF Gauge
        setText('eng_003_1', data[1]); // Text Value (though element removed? No, I should verify IDs)
        // Wait, I removed the text element id="eng_003_1" from index.html in the previous step?
        // Let's check index.html again. I removed the "maf-display" div which contained it.
        // But... I didn't add it back in the Boost panel? 
        // Ah, in the Boost panel I added: <canvas id="gauge_maf" ...> <div class="gauge-label-sm">MAF</div>
        // I did NOT add a text span for MAF value. 
        // The previous code had: <span class="stat-value" id="eng_003_1">--</span> in the Boost panel (Step 922/923). 
        // My replacement in Step 950 REMOVED the "maf-display" from perf-panel (good) and ADDED the canvas to boost-panel (good).
        // But the boost-panel replacement in Step 950 did NOT include the `eng_003_1` span.
        // So `setText('eng_003_1', ...)` will throw null reference error if I don't add the ID back or handle the null.
        // I should add the value text back, maybe inside the gauge wrapper or below it.

        let mafVal = data[1] && data[1].value !== undefined ? data[1].value : data[1];
        drawGauge('gauge_maf', mafVal, 0, 400, ['g/s','MAF']);
    }

    function updateEngine020(data) {
        // Group 20: Timing Retard Cyl 1-4
        updateKnockBar(1, data[0]);
        updateKnockBar(2, data[1]);
        updateKnockBar(3, data[2]);
        updateKnockBar(4, data[3]);
    }

    function updateKnockBar(cyl, val) {
        // Scale: 0-12 degrees. Red if > 3.
        let numVal = 0;
        if (val && val.value !== undefined) numVal = val.value;
        else if (typeof val === 'number') numVal = val;

        const maxRetard = 12.0;
        const pct = Math.min((numVal / maxRetard) * 100, 100);
        const bar = document.getElementById(`k_bar_${cyl}`);
        const txt = document.getElementById(`k_val_${cyl}`);

        if (bar) {
            bar.style.height = `${pct}%`;
            if (numVal <= 0.1) bar.style.backgroundColor = 'transparent';
            else if (numVal < 3) bar.style.backgroundColor = '#ffcc00'; // Yellow
            else bar.style.backgroundColor = '#ff0000'; // Red
        }
        if (txt) txt.textContent = numVal.toFixed(1);
    }

    function updateEngine106(data) {
        // Group 106: Fuel Rail (Spec/Act), Duty, Temp
        setText('eng_106_0', data[0]); // Spec (Labelled 'Specified')
        setText('eng_106_2', data[2]); // Duty
        // Temp removed from this panel, handled in group 134

        // Gauge for Actual (data[1])
        let actVal = data[1] && data[1].value !== undefined ? data[1].value : data[1];
        drawGauge('gauge_fuel', actVal, 0, 150, ['Bar', 'Actual']);
    }

    function updateEngine115(data) {
        // Group 115: RPM, Load, Boost Spec, Boost Actual
        setText('eng_115_2', data[2]); // Spec

        // Gauge for Actual (data[3])
        let actVal = data[3] && data[3].value !== undefined ? data[3].value : data[3];
        drawGauge('gauge_boost', actVal, 0, 3000, ['mbar', 'Actual']);
    }

    function updateEngine134(data) {
        setText('eng_134_0', data[0]);
        setText('eng_134_1', data[1]);
        setText('eng_134_2', data[2]);
        setText('eng_134_3', data[3]);
    }

    // --- Data Routing ---
    // The old socket.on('update_data') is replaced by the consolidated diagnostic_update handler.

    function updateTransClutch1(data) {
        // Group 11: Speed(G501), Torque(K1), Current(V1), Pressure(G193)
        // Values: [0, 1, 2, 3]

        setText('trans_11_0', data[0]); // Speed
        setText('trans_11_1', data[1]); // Torque
        setText('trans_11_2', data[2]); // Current
        // setText('trans_11_3', data[3]); // Pressure (Gauge Label) - Removed duplicate

        // Gauge
        drawGauge('gauge_pres_1', data[3].value, 0, 20, ['Bar', 'Clutch 1']);
    }

    function updateTransClutch2(data) {
        // Group 12: Speed(G502), Torque(K2), Current(V2), Pressure(G194)

        setText('trans_12_0', data[0]); // Speed
        setText('trans_12_1', data[1]); // Torque
        setText('trans_12_2', data[2]); // Current
        // setText('trans_12_3', data[3]); // Pressure (Gauge Label) - Removed duplicate

        // Gauge
        drawGauge('gauge_pres_2', data[3].value, 0, 20, ['Bar', 'Clutch 2']);
    }

    function updateTransSelector(data) {
        // Group 16: Travelers 1-3, 2-4, 5-N, 6-R
        updateBar('bar_sel_1', data[0].value);
        updateBar('bar_sel_2', data[1].value);
        updateBar('bar_sel_3', data[2].value);
        updateBar('bar_sel_4', data[3].value);
    }

    function updateTransTemp(data) {
        // Group 19: Fluid, Module, Clutch, Status
        setText('trans_19_0', data[0]);
        setText('trans_19_1', data[1]);
        setText('trans_19_2', data[2]);
        setText('trans_19_3', data[3]);
    }

    function updateAWDStatus(data) {
        // Group 1: Oil Temp, Plate Temp, Voltage, (Blank)
        setText('awd_1_0', data[0]);
        setText('awd_1_1', data[1]);
        setText('awd_1_2', data[2]);
    }

    function updateAWDPerf(data) {
        // Group 3: Pressure, Torque, Valve, Current
        drawGauge('gauge_awd_pres', data[0].value, 0, 60, ['Bar', 'Oil Pressure']); // High pressure pump
        // setText('awd_3_0', data[0]);

        drawGauge('gauge_awd_torque', data[1].value, 0, 2000, ['Nm', 'Est. Torque']);
        // setText('awd_3_1', data[1]);

        setText('awd_3_2', data[2]);
        setText('awd_3_3', data[3]);
    }

    function updateAWDModes(data) {
        // Group 5: CAN Out, Veh Mode, Slip Ctrl, Op Mode
        setText('awd_5_0', data[0]);
        setText('awd_5_1', data[1]);
        setText('awd_5_2', data[2]);
        setText('awd_5_3', data[3]);
    }

    // --- Helpers ---
    function setText(id, valObj) {
        const el = document.getElementById(id);
        if (el) el.textContent = `${toFixed(valObj.value)} ${valObj.unit}`;
    }

    function toFixed(val) {
        if (typeof val === 'number') return val.toFixed(1);
        return val;
    }

    // --- Visualization ---

    // Simple vertical bar centered at 50%
    function updateBar(id, val) {
        // Input: -100 to 100
        const el = document.getElementById(id);
        if (!el) return;

        // Normalize to 0-100% relative to container height?
        // But center zero means 0 is middle.
        // If val > 0: top: 50% - height, height: val/2 %
        // If val < 0: top: 50%, height: abs(val)/2 %

        let percentage = Math.abs(val) / 2; // scale 100 -> 50% height
        if (percentage > 50) percentage = 50;

        if (val >= 0) {
            el.style.top = (50 - percentage) + '%';
            el.style.height = percentage + '%';
            el.style.backgroundColor = '#ff3b3b';
        } else {
            el.style.top = '50%';
            el.style.height = percentage + '%';
            el.style.backgroundColor = '#3b3bff';
        }
    }

    function drawGauge(canvasId, value, min, max, label) {
        const canvas = document.getElementById(canvasId);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        const W = canvas.width;
        const H = canvas.height;
        const cx = W / 2;
        const cy = H / 2;
        const r = (W / 2) - 10;

        ctx.clearRect(0, 0, W, H);

        // Background Arc
        const startAngle = 0.75 * Math.PI;
        const endAngle = 2.25 * Math.PI;

        ctx.beginPath();
        ctx.arc(cx, cy, r, startAngle, endAngle);
        ctx.lineWidth = 15;
        ctx.strokeStyle = '#333';
        ctx.lineCap = 'round';
        ctx.stroke();

        // Value Arc
        const range = endAngle - startAngle;
        const clampedVal = Math.max(min, Math.min(max, value));
        const pct = (clampedVal - min) / (max - min);
        const valAngle = startAngle + (pct * range);

        ctx.beginPath();
        ctx.arc(cx, cy, r, startAngle, valAngle);
        ctx.lineWidth = 15;
        ctx.strokeStyle = '#ff3b3b';
        ctx.lineCap = 'round';
        ctx.stroke();

        // Text
        ctx.fillStyle = '#fff';
        ctx.font = 'bold 24px monospace';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(value.toFixed(1), cx, cy);

        ctx.font = '14px sans-serif';
        ctx.fillStyle = '#888';
        let labelArr = [];
        if (typeof label === 'string') {
            labelArr = label.split('\n');
        } else {
            labelArr = label;
        }

        for (let i = 0; i < labelArr.length; i++) {
            ctx.fillText(labelArr[i], cx, cy + 20 + (i * 15));
        }
    }
});
