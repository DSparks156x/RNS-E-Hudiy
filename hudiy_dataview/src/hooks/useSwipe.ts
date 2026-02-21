import { useCallback, useRef } from 'react';

interface SwipeOptions {
    onSwipeLeft?: () => void;
    onSwipeRight?: () => void;
    /** Minimum horizontal distance (px) before a swipe is recognised. Default: 50 */
    threshold?: number;
    /** Maximum vertical drift (px) allowed before the gesture is cancelled. Default: 80 */
    maxVertical?: number;
}

/**
 * Returns pointer-event handlers to attach to a container element.
 * Works for both touch and mouse input via the unified Pointer Events API.
 */
export function useSwipe({
    onSwipeLeft,
    onSwipeRight,
    threshold = 50,
    maxVertical = 80,
}: SwipeOptions) {
    const startX = useRef<number | null>(null);
    const startY = useRef<number | null>(null);

    const onPointerDown = useCallback((e: React.PointerEvent) => {
        startX.current = e.clientX;
        startY.current = e.clientY;
    }, []);

    const onPointerUp = useCallback(
        (e: React.PointerEvent) => {
            if (startX.current === null || startY.current === null) return;

            const dx = e.clientX - startX.current;
            const dy = e.clientY - startY.current;

            startX.current = null;
            startY.current = null;

            // Reject gesture if vertical drift is too large (scrolling, not swiping)
            if (Math.abs(dy) > maxVertical) return;

            if (dx < -threshold) {
                onSwipeLeft?.();
            } else if (dx > threshold) {
                onSwipeRight?.();
            }
        },
        [onSwipeLeft, onSwipeRight, threshold, maxVertical],
    );

    const onPointerCancel = useCallback(() => {
        startX.current = null;
        startY.current = null;
    }, []);

    return { onPointerDown, onPointerUp, onPointerCancel };
}
