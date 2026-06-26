'use client';

import useEmblaCarousel from 'embla-carousel-react';
import Image from 'next/image';
import { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

import type { ScreenshotItem } from '@/content/site.types';

type ScreenshotCarouselProps = {
  items: readonly ScreenshotItem[];
  label: string;
  previousLabel: string;
  nextLabel: string;
};

export function ScreenshotCarousel({
  items,
  label,
  previousLabel,
  nextLabel
}: ScreenshotCarouselProps) {
  const frameClassName =
    items[0]?.kind === 'mobile' ? 'shot-frame shot-frame--mobile' : 'shot-frame shot-frame--desktop';
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [emblaRef, emblaApi] = useEmblaCarousel({
    align: 'start',
    loop: items.length > 1
  });

  useEffect(() => {
    if (!emblaApi) {
      return;
    }

    const onSelect = () => setSelectedIndex(emblaApi.selectedScrollSnap());
    emblaApi.on('select', onSelect);
    onSelect();

    return () => {
      emblaApi.off('select', onSelect);
    };
  }, [emblaApi]);

  if (items.length === 0) {
    return null;
  }

  return (
    <div className={frameClassName}>
      <div className="shot-carousel" ref={emblaRef}>
        <div className="shot-carousel__container">
          {items.map((item) => (
            <figure className="shot-carousel__slide" key={item.src}>
              <div className="shot-device-shell">
                <Image
                  alt={item.alt}
                  className="shot-device-shell__image"
                  height={980}
                  priority={item === items[0]}
                  src={item.src}
                  width={1440}
                />
              </div>
              <figcaption>
                <span className="eyebrow">{label}</span>
                <p>{item.caption}</p>
              </figcaption>
            </figure>
          ))}
        </div>
      </div>
      {items.length > 1 ? (
        <div className="shot-controls">
          <button
            aria-label={previousLabel}
            className="icon-button"
            onClick={() => emblaApi?.scrollPrev()}
            type="button"
          >
            <ChevronLeft size={16} />
          </button>
          <div className="shot-dots" aria-hidden="true">
            {items.map((item, index) => (
              <span
                className={index === selectedIndex ? 'shot-dot shot-dot--active' : 'shot-dot'}
                key={item.src}
              />
            ))}
          </div>
          <button
            aria-label={nextLabel}
            className="icon-button"
            onClick={() => emblaApi?.scrollNext()}
            type="button"
          >
            <ChevronRight size={16} />
          </button>
        </div>
      ) : null}
    </div>
  );
}
