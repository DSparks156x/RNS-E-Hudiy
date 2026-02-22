interface InjectionBarProps {
    value: number;
}

export function InjectionBar({ value }: InjectionBarProps) {
    // Typical injection time at idle is ~1-3ms, WOT might be 15-20ms. Max 25ms.
    const maxTime = 25.0;
    const pct = Math.min((value / maxTime) * 100, 100);

    return (
        <div className="inj-container">
            <div className="inj-header">
                <span className="inj-label">Injection Time</span>
                <span className="inj-val">{value > 0 ? value.toFixed(1) + ' ms' : '--'}</span>
            </div>
            <div className="inj-bar-wrapper">
                <div className="inj-bar-track">
                    <div
                        className="inj-bar-fill"
                        style={{ width: `${pct}%` }}
                    />
                </div>
            </div>
        </div>
    );
}
