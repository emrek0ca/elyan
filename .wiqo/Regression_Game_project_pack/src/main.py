import pygame

def main():
    pygame.init()
    screen = pygame.display.set_mode((900, 520))
    pygame.display.set_caption("Wiqo Game Prototype")
    clock = pygame.time.Clock()
    running = True
    x = 100

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

        keys = pygame.key.get_pressed()
        if keys[pygame.K_RIGHT]:
            x += 4
        if keys[pygame.K_LEFT]:
            x -= 4

        screen.fill((16, 24, 40))
        pygame.draw.rect(screen, (120, 180, 255), (x, 280, 70, 70))
        pygame.display.flip()
        clock.tick(60)

    pygame.quit()

if __name__ == "__main__":
    main()
