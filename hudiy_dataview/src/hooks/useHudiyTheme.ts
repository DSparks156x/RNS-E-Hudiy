import { useEffect, useState } from 'react';
import { Socket } from 'socket.io-client';

// Hudiy provides a Material You-like color palette
export interface HudiyColorScheme {
    primary?: string;
    onSurface?: string;
    darkThemeEnabled?: boolean;
    background?: string;
    surface?: string;
    onBackground?: string;
    primaryContainer?: string;
    onPrimaryContainer?: string;
    surfaceVariant?: string;
    onSurfaceVariant?: string;
    outline?: string;
    outlineVariant?: string;
    [key: string]: any; // Catch-all for any other variables Hudiy sends
}

interface HudiyObj {
    colorScheme: HudiyColorScheme;
    onColorSchemeChanged?: () => void;
    onAttached?: () => void;
}

declare global {
    interface Window {
        hudiy?: HudiyObj;
    }
}

const DEFAULT_DEV_THEME: HudiyColorScheme = {
    primary: '#ff3b3b',
    onSurface: '#ffffff',
    darkThemeEnabled: true,
    background: '#121212',
    surface: '#1e1e1e',
    onBackground: '#e0e0e0',
    primaryContainer: '#6b0000',
    onPrimaryContainer: '#ffdad6',
    surfaceVariant: '#444444',
    onSurfaceVariant: '#c4c4c4',
    outline: '#8c8c8c',
    outlineVariant: '#444444'
};

export function useHudiyTheme(socket: Socket | null) {
    const [theme, setTheme] = useState<HudiyColorScheme>(DEFAULT_DEV_THEME);

    useEffect(() => {
        // If not running inside Hudiy host, abort.
        if (!window.hudiy) return;

        const h = window.hudiy;

        const updateColors = () => {
            if (h.colorScheme) {
                // Also send it to the backend so it shows up in the python terminal easily
                if (socket) {
                    socket.emit('log_theme', h.colorScheme);
                }
                setTheme({ ...h.colorScheme });
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

        return () => {
            h.onColorSchemeChanged = originalColorChanged;
            h.onAttached = originalAttached;
        };
    }, []);

    return { theme };
}
