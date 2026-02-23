import { useEffect, useState } from 'react';

interface HudiyColorScheme {
    primary?: string;
    onSurface?: string;
    darkThemeEnabled?: boolean;
}

interface HudiyObj {
    colorScheme: HudiyColorScheme;
    onColorSchemeChanged?: () => void;
    onAttached?: () => void;
    // Other callbacks aren't strictly needed for color mapping
}

declare global {
    interface Window {
        hudiy?: HudiyObj;
    }
}

export function useHudiyTheme() {
    const [primary, setPrimary] = useState('#ff3b3b'); // Default dev red
    const [onSurface, setOnSurface] = useState('#ffffff'); // Default dev white

    useEffect(() => {
        // If not running inside Hudiy host, abort.
        if (!window.hudiy) return;

        const h = window.hudiy;

        // We assume h.colorScheme is defined per API spec.
        const updateColors = () => {
            if (h.colorScheme) {
                if (h.colorScheme.primary) setPrimary(h.colorScheme.primary);
                if (h.colorScheme.onSurface) setOnSurface(h.colorScheme.onSurface);
            }
        };

        // Override the callbacks to trigger our React state sync
        const originalColorChanged = h.onColorSchemeChanged;
        const originalAttached = h.onAttached;

        h.onColorSchemeChanged = () => {
            updateColors();
            if (originalColorChanged) originalColorChanged();
        };

        h.onAttached = () => {
            updateColors();
            if (originalAttached) originalAttached();
        };

        // Run once on mount in case it attached before React rendered
        updateColors();

        // Not much we can do for cleanup since these callbacks are top-level properties on window.hudiy
        // but we can try reverting to original
        return () => {
            h.onColorSchemeChanged = originalColorChanged;
            h.onAttached = originalAttached;
        };
    }, []);

    return { primary, onSurface };
}
