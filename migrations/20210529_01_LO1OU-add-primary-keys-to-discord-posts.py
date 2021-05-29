"""
Add primary keys to discord_posts
"""

from yoyo import step

__depends__ = {'20210328_01_8tlz4-add-indexes-to-favorites-tables'}

steps = [
    step(
        """
            DELETE FROM discord_posts a
            USING discord_posts b
            WHERE a.ctid < b.ctid
            AND a.id = b.id
            AND a.server = b.server
            AND a.channel = b.channel;
        """
    ),
    step("ALTER TABLE discord_posts ADD PRIMARY KEY (id, server, channel); ")
]
